import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learnloop.api import create_app
from learnloop.persistence.database import Activity, Chunk, Submission
from learnloop.runtime.events import VALIDATORS
from learnloop.runtime.worker import work_once
from tests.conftest import COURSE_TEXT

pytestmark = pytest.mark.integration


def prepare(stack):
    client, factory, services, settings = stack
    course = client.post("/api/courses", json={"title": "Integration course"}).json()
    response = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("notes.txt", COURSE_TEXT.encode(), "text/plain")},
    )
    assert response.status_code == 202, response.text
    uploaded = response.json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{uploaded['runId']}").json()
    assert run["status"] == "completed", run
    return course["id"], uploaded


def test_upload_publication_search_and_scope(stack):
    client, factory, services, settings = stack
    course_id, uploaded = prepare(stack)
    course = client.get(f"/api/courses/{course_id}").json()
    assert course["documents"][0]["status"] == "published"
    assert len(course["graph"]["concepts"]) == 1
    duplicate = client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("same.txt", COURSE_TEXT.encode())},
    ).json()
    assert duplicate["duplicate"] and duplicate["runId"] == uploaded["runId"]
    found = client.post(f"/api/courses/{course_id}/search", json={"query": "gradient"}).json()
    assert len(found["passages"]) == 1
    assert client.get(f"/api/documents/{uploaded['documentId']}/pages/1").status_code == 200
    other = create_app(
        settings.model_copy(update={"local_owner_id": "another-owner"}),
        factory,
        services,
    )
    with TestClient(other) as stranger:
        stranger.headers["Authorization"] = "Bearer test-token"
        for path in [
            f"/api/courses/{course_id}",
            f"/api/agent-activity/runs/{uploaded['runId']}",
            f"/api/documents/{uploaded['documentId']}/pages/1",
        ]:
            assert stranger.get(path).status_code == 404
    assert client.get("/api/courses", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_pdf_slide_images_preserve_page_orientation_and_owner_scope(stack):
    import io
    import struct

    from pypdf import PdfWriter

    from learnloop.persistence.database import Document

    client, factory, services, settings = stack
    writer = PdfWriter()
    writer.add_blank_page(width=320, height=180)
    writer.add_blank_page(width=180, height=320)
    content = io.BytesIO()
    writer.write(content)
    course = client.post("/api/courses", json={"title": "Slide previews"}).json()
    uploaded = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("slides.pdf", content.getvalue(), "application/pdf")},
    ).json()
    with factory.begin() as db:
        db.get(Document, uploaded["documentId"]).pages = 2
    route = f"/api/documents/{uploaded['documentId']}/pages"
    for page in (1, 2):
        image = client.get(f"{route}/{page}/slide")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", image.content[16:24])
        assert max(width, height) == 1800
        assert (width > height) == (page == 1)
    assert client.get(f"{route}/0/slide").status_code == 404
    assert client.get(f"{route}/3/slide").status_code == 404
    assert (
        client.get(f"{route}/1/slide", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    other = create_app(
        settings.model_copy(update={"local_owner_id": "other-owner"}), factory, services
    )
    with TestClient(other) as stranger:
        stranger.headers["Authorization"] = "Bearer test-token"
        assert stranger.get(f"{route}/1/slide").status_code == 404
    text = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("notes.txt", COURSE_TEXT.encode())},
    ).json()
    assert client.get(f"/api/documents/{text['documentId']}/pages/1/slide").status_code == 415


def test_interactive_loop_hint_idempotency_and_atomic_evidence(stack):
    client, factory, services, settings = stack
    course_id, _ = prepare(stack)
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    assert work_once(factory, services)
    session_id = session["id"]
    for index in range(3):
        if index:
            client.post(
                f"/api/sessions/{session_id}/next", json={"expectedLearnerVersion": index}
            ).raise_for_status()
            assert work_once(factory, services)
        session = client.get(f"/api/sessions/{session_id}").json()
        activity = session["activity"]
        serialized = json.dumps(activity)
        assert (
            "correctChoiceId" not in serialized
            and "explanation" not in serialized
            and 'hint"' not in serialized
        )
        if index == 0:
            assert client.post(f"/api/activities/{activity['id']}/hint").json()["hintUsed"]
        body = {
            "operationId": f"answer-{index}",
            "expectedLearnerVersion": index,
            "choiceId": "a",
        }
        endpoint = f"/api/activities/{activity['id']}/responses"
        assert client.post(endpoint, json={**body, "correct": True}).status_code == 422
        result = client.post(endpoint, json=body)
        assert result.status_code == 202, result.text
        assert client.post(endpoint, json=body).json() == result.json()
        assert client.post(endpoint, json={**body, "choiceId": "b"}).status_code == 409
        assert client.post(f"/api/activities/{activity['id']}/hint").status_code == 409
        assert work_once(factory, services)
        saved = client.get(f"/api/submissions/{result.json()['submissionId']}").json()
        assert saved["assessment"]["learnerVersion"] == index + 1
        state = client.get(f"/api/courses/{course_id}/learner-state").json()
        evidence = next(iter(state["concepts"].values()))[activity["difficulty"]]
        assert state["version"] == index + 1
        assert activity["difficulty"] == "basic"
        assert evidence["state"] == ("demonstrated" if index == 2 else "developing")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 3
        assert db.scalar(select(func.count()).select_from(Activity)) == 3
    assert len(client.get(f"/api/courses/{course_id}/assessments").json()) == 3
    client.post(
        f"/api/sessions/{session_id}/next", json={"expectedLearnerVersion": 3}
    ).raise_for_status()
    assert work_once(factory, services)
    finished = client.get(f"/api/sessions/{session_id}").json()
    assert finished["activity"] is None and finished["notice"]


def test_paraphrased_sources_publish_and_allow_practice(stack):
    client, factory, services, settings = stack
    services.paraphrase_source = True
    course_id, uploaded = prepare(stack)
    course = client.get(f"/api/courses/{course_id}").json()
    assert course["documents"][0]["status"] == "published"
    assert course["graph"]["concepts"][0]["sources"][0]["quote"] not in COURSE_TEXT
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    assert work_once(factory, services)
    assert client.get(f"/api/sessions/{session['id']}").json()["activity"]


def test_expert_prepares_lessons_and_private_tests_for_tutor(stack):
    client, factory, services, settings = stack
    course_id, uploaded = prepare(stack)
    run_summaries = client.get(f"/api/courses/{course_id}/runs").json()
    prepared = next(run for run in run_summaries if run["id"] == uploaded["runId"])
    assert prepared["documentId"] == uploaded["documentId"] and prepared["startedAt"]
    assert prepared["sessionId"] is None
    learning = client.get(f"/api/courses/{course_id}/materials").json()
    assert learning["expectedCount"] == 1 and len(learning["materials"]) == 1
    material = learning["materials"][0]
    assert material["questionCount"] == 6
    assert material["lesson"]["workedExample"]["steps"]
    assert material["lesson"]["flashcards"] and material["sources"][0]["page"] == 1
    public = json.dumps(learning)
    assert "correctChoiceId" not in public and '"tests"' not in public and '"hint"' not in public
    review = client.get(f"/api/documents/{uploaded['documentId']}/review").json()
    assert "correctChoiceId" not in json.dumps(review)
    before = services.questions
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    run_summaries = client.get(f"/api/courses/{course_id}/runs").json()
    assert (
        next(run for run in run_summaries if run["id"] in session["runIds"])["sessionId"]
        == session["id"]
    )
    assert work_once(factory, services)
    activity = client.get(f"/api/sessions/{session['id']}").json()["activity"]
    assert activity["authoredBy"] == "expert"
    assert services.questions == before  # No on-demand tutoring generation.
    assert (
        client.post(f"/api/documents/{uploaded['documentId']}/materials").json()["status"]
        == "ready"
    )
    other = create_app(
        settings.model_copy(update={"local_owner_id": "another-owner"}), factory, services
    )
    with TestClient(other) as stranger:
        stranger.headers["Authorization"] = "Bearer test-token"
        assert stranger.get(f"/api/courses/{course_id}/materials").status_code == 404
        assert (
            stranger.post(f"/api/documents/{uploaded['documentId']}/materials").status_code == 404
        )


def test_material_generation_resumes_saved_lessons_and_keeps_graph_ids(stack, monkeypatch):
    from learnloop.agents.expert.materials import prepare_materials
    from learnloop.persistence.database import Document

    client, factory, services, settings = stack
    course_id, uploaded = prepare(stack)
    graph_before = client.get(f"/api/courses/{course_id}").json()["graph"]
    with factory() as db:
        before = db.get(Document, uploaded["documentId"]).graph["resources"]

    def no_more_model_calls(*args, **kwargs):
        raise AssertionError("Saved lessons must not be regenerated")

    monkeypatch.setattr(services, "generate", no_more_model_calls)
    prepare_materials(factory, services, uploaded["runId"], uploaded["documentId"])
    with factory() as db:
        assert db.get(Document, uploaded["documentId"]).graph["resources"] == before
    assert client.get(f"/api/courses/{course_id}").json()["graph"] == graph_before


def test_partial_material_backfill_retries_without_regenerating_saved_lesson(stack, monkeypatch):
    import copy

    from learnloop.core.errors import ServiceError
    from learnloop.persistence.database import Document

    client, factory, services, settings = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        original_concept = graph["concepts"][0]["id"]
        original_resource = copy.deepcopy(graph["resources"][original_concept])
        extra = {**graph["concepts"][0], "id": f"{doc.id}:learning-rate", "title": "Learning rate"}
        graph["concepts"].append(extra)
        doc.graph = graph
    endpoint = f"/api/documents/{uploaded['documentId']}/materials"
    run = client.post(endpoint).json()
    assert client.post(endpoint).json()["runId"] == run["runId"]
    original_generate = services.generate

    def fail_generation(*args, **kwargs):
        raise ServiceError("temporary_outage", "Generation temporarily unavailable.")

    monkeypatch.setattr(services, "generate", fail_generation)
    work_once(factory, services)
    snapshot = client.get(f"/api/agent-activity/runs/{run['runId']}").json()
    assert snapshot["status"] == "failed"
    assert len(client.get(f"/api/courses/{course_id}/materials").json()["materials"]) == 1
    monkeypatch.setattr(services, "generate", original_generate)
    client.post(
        f"/api/agent-activity/runs/{run['runId']}/commands",
        json={
            "kind": "retry",
            "operationId": "resume-materials",
            "expectedVersion": snapshot["recordVersion"],
        },
    ).raise_for_status()
    work_once(factory, services)
    learning = client.get(f"/api/courses/{course_id}/materials").json()
    assert len(learning["materials"]) == 2
    with factory() as db:
        assert (
            db.get(Document, uploaded["documentId"]).graph["resources"][original_concept]
            == original_resource
        )


def test_full_section_review_expands_catalog_without_resetting_saved_learning(stack, monkeypatch):
    import copy

    from learnloop.core.schemas import SectionGraph
    from learnloop.persistence.database import Document, LearnerState

    client, factory, services, settings = stack
    course_id, uploaded = prepare(stack)
    doc_id = uploaded["documentId"]
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        graph = copy.deepcopy(doc.graph)
        graph.pop("analysis")  # Simulate an existing sampled document.
        original_id = graph["concepts"][0]["id"]
        original_resource = copy.deepcopy(graph["resources"][original_id])
        doc.graph = graph
        for i in range(24):
            db.add(
                Chunk(
                    id=f"additional-{i}",
                    document_id=doc_id,
                    course_id=course_id,
                    ordinal=i + 1,
                    page=i + 2,
                    text=f"Distinct learning goal number {i}. " + COURSE_TEXT,
                )
            )
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id))
        state.evidence = {original_id: {"basic": {"state": "demonstrated"}}}
        state.version = 4
    original_generate = services.generate
    reviewed = []

    def generate(role, instruction, context, output):
        if output is SectionGraph:
            concepts = []
            for i, passage in enumerate(context["passages"]):
                reviewed.append(passage["chunkId"])
                concepts.append(
                    {
                        "id": f"goal-{i}",
                        "title": "Gradient descent"
                        if "Distinct learning goal" not in passage["text"]
                        else f"Distinct goal {passage['chunkId']}",
                        "summary": "A separately teachable goal supported by this section.",
                        "sources": [{"chunkId": passage["chunkId"], "quote": passage["text"][:60]}],
                    }
                )
            return SectionGraph.model_validate({"concepts": concepts, "prerequisites": []})
        return original_generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", generate)
    endpoint = f"/api/documents/{doc_id}/analyze"
    run = client.post(endpoint).json()
    assert client.post(endpoint).json()["runId"] == run["runId"]
    assert work_once(factory, services)
    assert len(reviewed) == len(set(reviewed)) == 25
    detail = client.get(f"/api/courses/{course_id}").json()
    assert len(detail["graph"]["concepts"]) == 25
    coverage = detail["documents"][0]["coverage"]
    assert coverage["processedPassages"] == coverage["totalPassages"] == 25
    with factory() as db:
        assert db.get(Document, doc_id).graph["resources"][original_id] == original_resource
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 4
    assert client.post(endpoint).json()["status"] == "ready"


def test_section_review_resume_only_reprocesses_failed_section(stack, monkeypatch):
    from collections import Counter

    from learnloop.core.errors import ServiceError
    from learnloop.core.schemas import SectionGraph

    client, factory, services, settings = stack
    calls = Counter()
    original = services.generate

    def generate(role, instruction, context, output):
        if output is SectionGraph:
            section = context["section"]
            calls[section] += 1
            if section == 2 and calls[section] == 1:
                raise ServiceError("section_timeout", "A section request timed out.")
        return original(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", generate)
    course = client.post("/api/courses", json={"title": "Section resume"}).json()
    upload = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("long-notes.txt", (COURSE_TEXT * 160).encode())},
    ).json()
    work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{upload['runId']}").json()
    assert run["status"] == "failed" and len(calls) >= 3
    client.post(
        f"/api/agent-activity/runs/{upload['runId']}/commands",
        json={
            "kind": "retry",
            "operationId": "resume-sections",
            "expectedVersion": run["recordVersion"],
        },
    ).raise_for_status()
    assert work_once(factory, services)
    assert client.get(f"/api/agent-activity/runs/{upload['runId']}").json()["status"] == "completed"
    assert calls[2] == 2 and all(count == 1 for section, count in calls.items() if section != 2)


def test_unresolved_sources_are_blocked_before_publication_or_practice(stack):
    client, factory, services, settings = stack
    services.bad_source = True
    course_id = client.post("/api/courses", json={"title": "Source validation"}).json()["id"]
    uploaded = client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("notes.txt", COURSE_TEXT.encode())},
    ).json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{uploaded['runId']}").json()
    assert run["status"] == "needs_review"
    assert run["error"]["code"] == "invalid_source"
    assert run["references"] == []
    assert client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"] == []
    session = client.post(f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0})
    assert session.status_code == 409
    assert (
        client.post(f"/api/courses/{course_id}/search", json={"query": "gradient"}).json()[
            "passages"
        ]
        == []
    )


def test_retry_receipts_and_sse_replay_match_frontend_contract(stack):
    client, factory, services, settings = stack
    course_id = client.post("/api/courses", json={"title": "Recovery"}).json()["id"]
    uploaded = client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("notes.txt", COURSE_TEXT.encode())},
    ).json()
    services.fail_next = True
    work_once(factory, services)
    run_id = uploaded["runId"]
    run = client.get(f"/api/agent-activity/runs/{run_id}").json()
    assert run["status"] == "failed" and run["allowedCommands"] == ["retry"]
    endpoint = f"/api/agent-activity/runs/{run_id}/commands"
    command = {
        "kind": "retry",
        "operationId": "retry-stable",
        "expectedVersion": run["recordVersion"],
    }
    first = client.post(endpoint, json=command)
    assert first.status_code == 200
    assert client.post(endpoint, json=command).json() == first.json()
    assert client.post(endpoint, json={**command, "expectedVersion": 999}).status_code == 409
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{run_id}").json()
    assert run["status"] == "completed"
    VALIDATORS["snapshot"].validate(run)
    stream = client.get(
        f"/api/agent-activity/runs/{run_id}/events?after_sequence=1",
        headers={"Last-Event-ID": "2"},
    )
    events = [
        json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")
    ]
    assert events[0]["sequence"] == 3 and events[-1]["sequence"] == run["lastSequence"]
    for event in events:
        VALIDATORS["event"].validate(event)
    assert (
        client.get(f"/api/agent-activity/runs/{run_id}/events?after_sequence=9999").status_code
        == 409
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 1


def test_stale_version_rejected_and_new_session_resumes_existing_activity(stack):
    client, factory, services, settings = stack
    course_id, _ = prepare(stack)
    endpoint = f"/api/courses/{course_id}/sessions"
    assert client.post(endpoint, json={"expectedLearnerVersion": 99}).status_code == 409
    session = client.post(endpoint, json={"expectedLearnerVersion": 0}).json()
    work_once(factory, services)
    resumed = client.post(endpoint, json={"expectedLearnerVersion": 0}).json()
    assert resumed["id"] == session["id"]
    activity_id = resumed["activity"]["id"]
    assert (
        client.post(
            f"/api/activities/{activity_id}/responses",
            json={
                "operationId": "stale",
                "expectedLearnerVersion": 99,
                "choiceId": "a",
            },
        ).status_code
        == 409
    )
    assert client.post(f"/api/sessions/{session['id']}/end").status_code == 200
    assert client.post(f"/api/activities/{activity_id}/hint").status_code == 409


def test_assessment_waits_for_explicit_next_and_retry_keeps_evidence_once(stack, monkeypatch):
    from learnloop.agents.assessing.agent import run as assess

    client, factory, services, _settings = stack
    course_id, _ = prepare(stack)
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    work_once(factory, services)
    activity = client.get(f"/api/sessions/{session['id']}").json()["activity"]
    submission = client.post(
        f"/api/activities/{activity['id']}/responses",
        json={
            "operationId": "once",
            "expectedLearnerVersion": 0,
            "choiceId": "a",
        },
    ).json()
    original = services.generate

    def no_tutoring(role, *args):
        assert role != "Tutoring", "Assessment must not advance to tutoring"
        return original(role, *args)

    monkeypatch.setattr(services, "generate", no_tutoring)
    work_once(factory, services)
    for _ in range(3):
        current = client.get(f"/api/sessions/{session['id']}").json()
        assert current["activity"]["id"] == activity["id"]
        assert current["activity"]["status"] == "assessed"
        assert current["assessment"] and current["selectedChoiceId"] == "a"
    assert not work_once(factory, services)  # Reading feedback creates no job.
    assess(factory, services, submission["runId"])
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1
    monkeypatch.setattr(services, "generate", original)
    client.post(
        f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": 1}
    ).raise_for_status()
    loading = client.get(f"/api/sessions/{session['id']}").json()
    assert loading["activity"] is None and loading["assessment"] is None
    # Repeated clicks cannot queue duplicate next questions.
    assert (
        client.post(
            f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": 1}
        ).status_code
        == 409
    )
    assert work_once(factory, services)
    following = client.get(f"/api/sessions/{session['id']}").json()
    assert following["activity"]["id"] != activity["id"]
    assert following["activity"]["status"] == "pending"
    assert following["assessment"] is None and following["selectedChoiceId"] is None
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1


def test_assessment_commit_failure_rolls_back_evidence_and_events_together(stack, monkeypatch):
    from learnloop.agents.assessing import agent as assessing
    from learnloop.core.errors import ServiceError

    client, factory, services, _settings = stack
    course_id, _ = prepare(stack)
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    work_once(factory, services)
    activity = client.get(f"/api/sessions/{session['id']}").json()["activity"]
    submission = client.post(
        f"/api/activities/{activity['id']}/responses",
        json={"operationId": "atomic", "expectedLearnerVersion": 0, "choiceId": "a"},
    ).json()
    original = assessing.accept

    def fail_commit(db, run_id, scope, committed=None):
        if scope == "learner_state":
            db.flush()
            raise ServiceError("test_commit_failure", "Commit was interrupted.")
        return original(db, run_id, scope, committed)

    monkeypatch.setattr(assessing, "accept", fail_commit)
    work_once(factory, services)
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0
    assert client.get(f"/api/submissions/{submission['submissionId']}").json()["assessment"] is None
    run = client.get(f"/api/agent-activity/runs/{submission['runId']}").json()
    assert not run["committedChanges"]
    assert not any(
        e["type"] == "runtime.validation" and e["payload"]["status"] == "accepted"
        for e in run["events"]
    )


def test_expired_job_lease_is_reclaimed_without_duplicate_chunks(stack):
    from datetime import timedelta

    from learnloop.persistence.database import Job, now

    client, factory, services, _settings = stack
    course_id = client.post("/api/courses", json={"title": "Recovery after restart"}).json()["id"]
    upload = client.post(
        f"/api/courses/{course_id}/documents", files={"file": ("notes.txt", COURSE_TEXT.encode())}
    ).json()
    with factory.begin() as db:
        job = db.scalar(select(Job).where(Job.run_id == upload["runId"]))
        job.status, job.attempts, job.lease_until = "running", 1, now() - timedelta(seconds=1)
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{upload['runId']}").json()
    assert run["status"] == "completed"
    with factory() as db:
        assert db.scalar(select(Job).where(Job.run_id == upload["runId"])).attempts == 2
        assert db.scalar(select(func.count()).select_from(Chunk)) == 1


def test_expired_lease_does_not_start_work_or_consume_attempt_while_other_worker_holds_lock(stack):
    from datetime import timedelta

    from learnloop.persistence.database import Job, now

    client, factory, services, _settings = stack
    course_id = client.post("/api/courses", json={"title": "Slow worker"}).json()["id"]
    upload = client.post(
        f"/api/courses/{course_id}/documents", files={"file": ("notes.txt", COURSE_TEXT.encode())}
    ).json()
    run_id = upload["runId"]
    with factory.begin() as db:
        job = db.scalar(select(Job).where(Job.run_id == run_id))
        job.status, job.attempts, job.lease_until = "running", 1, now() - timedelta(seconds=1)
    from filelock import FileLock

    with FileLock(str(factory.kw["bind"].url.database) + ".worker.lock"):
        assert work_once(factory, services) is False
        with factory() as db:
            assert db.scalar(select(Job).where(Job.run_id == run_id)).attempts == 1
    assert work_once(factory, services)
