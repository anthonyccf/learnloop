from tests.release_fixtures import seed_legacy_release
import copy

from sqlalchemy import select

from learnloop.agents.expert.materials import material_content, material_valid
from learnloop.core.grounding import grounding_fingerprint
from learnloop.core.schemas import Question
from learnloop.persistence.database import Chunk, Document, LearnerState
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare as prepare_curriculum


def prepare(stack):
    """The explicit-target API remains supported for legacy, unassigned concepts."""
    course_id, uploaded = prepare_curriculum(stack)
    with stack[1].begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        graph.pop("curriculum", None)
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    return course_id, uploaded


def test_curriculum_target_matches_layer_and_preserves_old_evidence(stack):
    client, factory, _, _ = stack
    course_id, _ = prepare_curriculum(stack)
    concept = client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"][0]
    assert concept["curriculum"]["layer"] == concept["targetDifficulty"] == "basic"
    with factory.begin() as db:
        record = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id))
        record.evidence = {
            concept["id"]: {
                "intermediate": {"state": "demonstrated"},
                "basic": {"state": "developing"},
            }
        }
    before = client.get(f"/api/courses/{course_id}/learner-state").json()
    assert before["overallStates"][concept["id"]] == "developing"
    endpoint = f"/api/courses/{course_id}/concepts/{concept['id']}/target"
    assert (
        client.post(
            endpoint, json={"targetDifficulty": "advanced", "expectedLearnerVersion": 0}
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint, json={"targetDifficulty": "basic", "expectedLearnerVersion": 0}
        ).status_code
        == 200
    )
    assert client.get(f"/api/courses/{course_id}/learner-state").json() == before


def test_advanced_target_drives_assignment_and_separate_evidence(stack):
    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    detail = client.get(f"/api/courses/{course_id}").json()
    concept_id = detail["graph"]["concepts"][0]["id"]
    endpoint = f"/api/courses/{course_id}/concepts/{concept_id}/target"
    assert (
        client.post(
            endpoint, json={"targetDifficulty": "expert", "expectedLearnerVersion": 0}
        ).status_code
        == 422
    )
    response = client.post(
        endpoint, json={"targetDifficulty": "advanced", "expectedLearnerVersion": 0}
    )
    assert response.status_code == 200
    assert response.json()["learnerVersion"] == 1
    assert (
        client.post(
            endpoint, json={"targetDifficulty": "basic", "expectedLearnerVersion": 0}
        ).status_code
        == 409
    )
    after = client.get(f"/api/courses/{course_id}").json()
    assert after["graph"]["organization"] == detail["graph"]["organization"]
    assert after["graph"]["prerequisites"] == detail["graph"]["prerequisites"]
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 1}
    ).json()
    assert work_once(factory, services)
    for index in range(2):
        current = client.get(f"/api/sessions/{session['id']}").json()
        assert current["activity"]["difficulty"] == "advanced"
        client.post(
            f"/api/activities/{current['activity']['id']}/responses",
            json={
                "operationId": f"advanced-{index}",
                "expectedLearnerVersion": index + 1,
                "choiceId": "a",
            },
        ).raise_for_status()
        assert work_once(factory, services)
        state = client.get(f"/api/courses/{course_id}/learner-state").json()
        assert state["overallStates"][concept_id] == (
            "developing" if index == 0 else "demonstrated"
        )
        assert set(state["concepts"][concept_id]) == {"advanced"}
        if index == 0:
            client.post(
                f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": 2}
            ).raise_for_status()
            assert work_once(factory, services)
    material = client.get(f"/api/courses/{course_id}/materials").json()["materials"][0]
    assert material["questionCountsByDifficulty"] == {"basic": 2, "intermediate": 2, "advanced": 2}
    assert "correctChoiceId" not in str(material)


def test_legacy_bank_upgrades_by_adding_levels_without_rewriting_existing_content(stack):
    client, factory, services, _ = stack
    course_id, uploaded = prepare_curriculum(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        key, pack = next(iter(graph["resources"].items()))
        pack["tests"] = [q for q in pack["tests"] if q["difficulty"] == "intermediate"]
        pack.pop("lessonsByDifficulty", None)
        for q in pack["tests"]:
            q.pop("difficulty")
        chunks = {
            c.id: {"text": c.text}
            for c in db.scalars(select(Chunk).where(Chunk.document_id == doc.id))
        }
        pack["grounding"] = {
            "status": "supported",
            "fingerprint": grounding_fingerprint(material_content(pack), chunks),
        }
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
        before = copy.deepcopy(pack)
    learner_before = client.get(f"/api/courses/{course_id}/learner-state").json()
    assert (
        client.get(f"/api/courses/{course_id}/materials").json()["materials"][0]["questionCount"]
        == 2
    )
    response = client.post(f"/api/documents/{uploaded['documentId']}/materials").json()
    assert response["status"] == "queued"
    assert work_once(factory, services)
    with factory() as db:
        updated = db.get(Document, uploaded["documentId"]).graph["resources"][key]
        assert updated["lesson"] == before["lesson"] and updated["tests"][:2] == before["tests"]
        assert len(updated["tests"]) == 6 and material_valid(updated, chunks)
        assert not updated.get("lessonsByDifficulty")
    assert client.get(f"/api/courses/{course_id}/learner-state").json() == learner_before


def test_target_change_keeps_lower_level_evidence_without_conveying_higher_mastery(stack):
    client, factory, _, _ = stack
    course_id, _ = prepare(stack)
    concept_id = client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"][0]["id"]
    with factory.begin() as db:
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id))
        state.evidence = {concept_id: {"basic": {"state": "demonstrated"}}}
    endpoint = f"/api/courses/{course_id}/concepts/{concept_id}/target"
    client.post(
        endpoint, json={"targetDifficulty": "basic", "expectedLearnerVersion": 0}
    ).raise_for_status()
    assert (
        client.get(f"/api/courses/{course_id}/learner-state").json()["overallStates"][concept_id]
        == "demonstrated"
    )
    client.post(
        endpoint, json={"targetDifficulty": "advanced", "expectedLearnerVersion": 1}
    ).raise_for_status()
    state = client.get(f"/api/courses/{course_id}/learner-state").json()
    assert state["overallStates"][concept_id] == "unassessed"
    assert state["concepts"][concept_id]["basic"]["state"] == "demonstrated"


def test_fallback_cannot_relabel_a_question_at_the_wrong_difficulty(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        concept_id = graph["concepts"][0]["id"]
        graph["resources"][concept_id]["tests"] = []
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    client.post(
        f"/api/courses/{course_id}/concepts/{concept_id}/target",
        json={"targetDifficulty": "advanced", "expectedLearnerVersion": 0},
    ).raise_for_status()
    original = services.generate

    def generate(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Question:
            assert context["difficulty"] == "advanced"
            result.difficulty = "basic"
        return result

    monkeypatch.setattr(services, "generate", generate)
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 1}
    ).json()
    assert work_once(factory, services)
    assert client.get(f"/api/sessions/{session['id']}").json()["activity"] is None
    run_id = session["runIds"][-1]
    assert (
        client.get(f"/api/agent-activity/runs/{run_id}").json()["error"]["code"]
        == "invalid_difficulty"
    )
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1
