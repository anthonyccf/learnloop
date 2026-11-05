import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, update

from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Chunk, CourseRelease, Document
from learnloop.persistence.releases import get_release, publish_course, scope_fingerprint
from learnloop.persistence.repository import course_graph
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare


def test_discovered_graph_is_staged_until_all_resources_validate(stack):
    from learnloop.agents.expert.agent import prepare_graph

    client, factory, services, _ = stack
    course = client.post("/api/courses", json={"title": "Staged course"}).json()["id"]
    upload = client.post(
        f"/api/courses/{course}/documents",
        files={
            "file": ("source.txt", b"Gradient descent subtracts the gradient to reduce the loss.")
        },
    ).json()
    prepare_graph(factory, services, upload["runId"])
    with factory() as db:
        assert db.get(Document, upload["documentId"]).status == "prepared"
        assert get_release(db, course) is None
    assert client.get(f"/api/courses/{course}").json()["graph"]["concepts"] == []
    assert client.get(f"/api/courses/{course}/materials").json()["materials"] == []
    assert (
        client.post(
            f"/api/courses/{course}/sessions", json={"expectedLearnerVersion": 0}
        ).status_code
        == 409
    )
    assert client.post(f"/api/courses/{course}/releases").status_code == 409
    assert work_once(factory, services)
    assert client.get(f"/api/courses/{course}").json()["release"]["version"] == 1


@pytest.mark.parametrize(
    "fault",
    ["missing_pack", "stale_source", "scope", "quiz_level", "curriculum", "pending_document"],
)
def test_incomplete_rebuild_keeps_previous_release(stack, fault):
    client, factory, _, _ = stack
    course, upload = prepare(stack)
    before = client.get(f"/api/courses/{course}").json()
    materials = client.get(f"/api/courses/{course}/materials").json()
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        concept = graph["concepts"][0]["id"]
        if fault == "missing_pack":
            graph["resources"].pop(concept)
        elif fault == "stale_source":
            db.scalar(
                select(Chunk).where(Chunk.document_id == doc.id)
            ).text = "Different draft evidence."
        elif fault == "scope":
            graph["resources"][concept]["scopeFingerprint"] = "stale"
        elif fault == "quiz_level":
            graph["resources"][concept]["tests"] = graph["resources"][concept]["tests"][:2]
        elif fault == "curriculum":
            graph["curriculum"]["signature"] = "stale"
        else:
            doc.status = "needs_review"
        doc.graph = graph
    assert client.post(f"/api/courses/{course}/releases").status_code == 409
    after = client.get(f"/api/courses/{course}").json()
    assert after["release"] == before["release"] and after["graph"] == before["graph"]
    assert client.get(f"/api/courses/{course}/materials").json() == materials


def test_release_retry_is_atomic_and_concurrent_publish_is_idempotent(stack):
    client, factory, _, _ = stack
    course, _ = prepare(stack)

    def publish(_):
        with factory.begin() as db:
            return publish_course(db, course).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(publish, range(2)))) == 1
    assert len(client.get(f"/api/courses/{course}/releases").json()["releases"]) == 1
    with pytest.raises(RuntimeError), factory.begin() as db:
        doc = db.scalar(select(Document).where(Document.course_id == course))
        doc.filename = "Revised label.txt"
        db.flush()
        assert publish_course(db, course).version == 2
        raise RuntimeError("Controlled rollback")
    assert len(client.get(f"/api/courses/{course}/releases").json()["releases"]) == 1


def test_sessions_and_assessment_stay_pinned_while_new_release_is_published(stack):
    client, factory, services, _ = stack
    course, upload = prepare(stack)
    old_release = client.get(f"/api/courses/{course}").json()["release"]
    session = client.post(
        f"/api/courses/{course}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    assert session["releaseId"] == old_release["id"]
    # Change valid metadata and publish a second complete snapshot.
    with factory.begin() as db:
        db.get(Document, upload["documentId"]).filename = "Second release.txt"
    new_release = client.post(f"/api/courses/{course}/releases").json()
    assert new_release["version"] == 2
    assert work_once(factory, services)
    current = client.get(f"/api/sessions/{session['id']}").json()
    assert current["releaseId"] == old_release["id"]
    assert current["activity"]["sources"][0]["label"] == "notes.txt"
    old_materials = client.get(
        f"/api/courses/{course}/materials", params={"releaseId": old_release["id"]}
    ).json()
    assert old_materials["materials"][0]["filename"] == "notes.txt"
    response = client.post(
        f"/api/activities/{current['activity']['id']}/responses",
        json={"operationId": "pinned-answer", "expectedLearnerVersion": 0, "choiceId": "a"},
    ).json()
    assert work_once(factory, services)
    assert client.get(f"/api/submissions/{response['submissionId']}").json()["status"] == "assessed"
    client.post(f"/api/sessions/{session['id']}/end").raise_for_status()
    fresh = client.post(
        f"/api/courses/{course}/sessions", json={"expectedLearnerVersion": 1}
    ).json()
    assert fresh["releaseId"] == new_release["id"]


def test_release_ownership_privacy_immutability_and_integrity(stack):
    client, factory, _, _ = stack
    course, _ = prepare(stack)
    release = client.get(f"/api/courses/{course}/releases").json()["releases"][0]
    assert "correctChoiceId" not in str(release) and "payload" not in release
    assert client.get("/api/courses/foreign/releases").status_code == 404
    foreign = client.post("/api/courses", json={"title": "Another course"}).json()["id"]
    assert (
        client.get(
            f"/api/courses/{foreign}/materials", params={"releaseId": release["id"]}
        ).status_code
        == 422
    )
    with pytest.raises(ValueError, match="immutable"), factory.begin() as db:
        db.get(CourseRelease, release["id"]).version = 99
    # Simulate corruption bypassing ORM guards: reads must fail closed.
    with factory.begin() as db:
        db.execute(
            update(CourseRelease).where(CourseRelease.id == release["id"]).values(sha256="0" * 64)
        )
    with factory() as db, pytest.raises(ServiceError, match="integrity"):
        course_graph(db, course)


def test_evaluation_export_pins_the_release_not_mutable_preparation(stack, tmp_path, monkeypatch):
    from learnloop.agents.expert.organization import catalog_signature
    from learnloop.evaluation.__main__ import export_unit
    from learnloop.evaluation.artifacts import thaw
    from learnloop.persistence import database

    _, factory, _, _ = stack
    course, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        template = graph["concepts"][0]
        resource = next(iter(graph["resources"].values()))
        graph["concepts"] = [
            {**template, "id": f"{doc.id}:c{i}", "title": f"Goal {i}"} for i in range(10)
        ]
        signature = catalog_signature(graph["concepts"])
        graph["organization"]["signature"] = signature
        graph["organization"]["topics"][0]["conceptIds"] = [c["id"] for c in graph["concepts"]]
        graph["curriculum"]["signature"] = signature
        graph["curriculum"]["objectives"] = {
            c["id"]: {
                "conceptId": c["id"],
                "layer": "basic",
                "teaches": c["title"] + " source-backed foundation",
                "assumes": [],
                "adds": "Understand the assigned foundation.",
            }
            for c in graph["concepts"]
        }
        graph["resources"] = {
            c["id"]: {
                **copy.deepcopy(resource),
                "scopeFingerprint": scope_fingerprint(
                    resource["lesson"], graph["curriculum"]["objectives"][c["id"]]
                ),
            }
            for c in graph["concepts"]
        }
        doc.graph = graph
        db.flush()
        release = publish_course(db, course)
    with factory.begin() as db:
        db.get(Document, upload["documentId"]).graph = {}
    monkeypatch.setattr(database, "session_factory", lambda: factory)
    export_unit(upload["documentId"], 0, 10, tmp_path / "unit", release.id)
    provenance = thaw(tmp_path / "unit/release-provenance.json")["payload"]
    assert provenance["releaseId"] == release.id and provenance["releaseHash"] == release.sha256
    assert len(thaw(tmp_path / "unit/unit.json")["payload"]["graph"]["concepts"]) == 10
