from tests.release_fixtures import seed_legacy_release
import copy

import pytest
from sqlalchemy import select

from learnloop.agents.assessing.agent import run as assess_run
from learnloop.core.domain import select_concept
from learnloop.core.schemas import Assessment
from learnloop.persistence.database import Document, Submission
from learnloop.runtime.worker import work_once
from tests.api.test_difficulty import prepare


def focused_session(stack, course_id, concept_id):
    client, factory, services, _ = stack
    session = client.post(
        f"/api/courses/{course_id}/sessions",
        json={"expectedLearnerVersion": 0, "conceptId": concept_id},
    ).json()
    assert work_once(factory, services)
    return session["id"]


def answer(stack, session_id, course_id, choice, number, reasoning=None):
    client, factory, services, _ = stack
    current = client.get(f"/api/sessions/{session_id}").json()
    activity = current["activity"]
    version = client.get(f"/api/courses/{course_id}/learner-state").json()["version"]
    receipt = client.post(
        f"/api/activities/{activity['id']}/responses",
        json={
            "operationId": f"answer-{number}",
            "expectedLearnerVersion": version,
            "choiceId": choice,
            "reasoning": reasoning,
        },
    )
    receipt.raise_for_status()
    assert work_once(factory, services)
    current = client.get(f"/api/sessions/{session_id}").json()
    state = client.get(f"/api/courses/{course_id}/learner-state").json()
    return current, state, receipt.json()


def continue_same_topic(stack, session_id, course_id, concept_id, state):
    client, factory, services, _ = stack
    if state["overallStates"][concept_id] == "demonstrated":
        # Continuing normally advances to a new topic. These tests explicitly
        # request extra practice to exercise contradictions after demonstration.
        client.post(
            f"/api/courses/{course_id}/sessions",
            json={"expectedLearnerVersion": state["version"], "conceptId": concept_id},
        ).raise_for_status()
    else:
        client.post(
            f"/api/sessions/{session_id}/next",
            json={"expectedLearnerVersion": state["version"]},
        ).raise_for_status()
    assert work_once(factory, services)


def test_review_confirmed_weakness_remediation_recovery_and_prerequisites_preserve_history(stack):
    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        parent = graph["concepts"][0]
        parent_id = parent["id"]
        child_id = parent_id + "-dependent"
        graph["concepts"].append({**parent, "id": child_id, "title": "Dependent goal"})
        graph["prerequisites"] = [
            {"prerequisite": parent_id, "dependent": child_id, "source": parent["sources"][0]}
        ]
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    session_id = focused_session(stack, course_id, parent_id)
    activity_ids, assessment_ids = [], []
    states = [
        "developing",
        "demonstrated",
        "review_due",
        "developing",
        "developing",
        "developing",
        "developing",
        "demonstrated",
    ]
    levels = ["intermediate"] * 4 + ["basic"] * 2 + ["intermediate"] * 2
    confirmed_snapshot = None
    for index, choice in enumerate(["a", "a", "b", "b", "a", "a", "a", "a"]):
        current, state, receipt = answer(stack, session_id, course_id, choice, index)
        activity_ids.append(current["activity"]["id"])
        assessment_ids.append(receipt["submissionId"])
        evidence = state["concepts"][parent_id]["intermediate"]
        assert state["overallStates"][parent_id] == states[index]
        assert current["activity"]["difficulty"] == levels[index]
        if index == 2:
            assert current["assessment"]["evidenceOutcome"] == "contradiction"
            assert not current["assessment"]["confirmedWeakness"]
        if index == 3:
            assert current["assessment"]["confirmedWeakness"]
            assert current["assessment"]["evidenceOutcome"] == "confirmed_weakness"
            assert evidence["confirmedWeakness"]["assessmentIds"] == assessment_ids[2:4]
            assert evidence["independentHistoryActivityIds"] == activity_ids[:2]
            assert all(c["status"] == "confirmed_weakness" for c in evidence["contradictions"])
            confirmed_snapshot = copy.deepcopy(evidence)
            # Re-running an already committed assessment must not add a failure or history.
            assess_run(factory, services, receipt["runId"])
            assert client.get(f"/api/courses/{course_id}/learner-state").json() == state
        if index in (4, 5):
            assert (
                evidence == confirmed_snapshot
            )  # Lower-level work cannot resolve target weakness.
        if index in (2, 3, 4, 5, 6):
            # Automatic recommendations still respect prerequisite evidence.
            assert select_concept(graph, state["concepts"], child_id) is None
        if index == 6:
            assert current["assessment"]["evidenceOutcome"] == "recovery_progress"
        if index < 7:
            continue_same_topic(stack, session_id, course_id, parent_id, state)
    assert evidence["confirmedWeakness"]["status"] == "resolved"
    assert evidence["confirmedWeakness"]["assessmentIds"] == assessment_ids[2:4]
    assert evidence["independentHistoryActivityIds"] == activity_ids[:2] + activity_ids[6:8]
    assert evidence["assessmentIds"] == assessment_ids[:4] + assessment_ids[6:8]
    assert all(c["status"] == "resolved" for c in evidence["contradictions"])
    assert evidence["weaknessHistory"][0]["activityIds"] == activity_ids[2:4]
    with factory() as db:
        assert sum(bool(s.assessment) for s in db.scalars(select(Submission))) == 8
    assert (
        client.post(
            f"/api/courses/{course_id}/sessions",
            json={"expectedLearnerVersion": state["version"], "conceptId": child_id},
        ).status_code
        == 202
    )


@pytest.mark.parametrize("uncertain,expected", [(False, "developing"), (True, "review_due")])
def test_certain_partial_rubric_failures_can_confirm_but_uncertainty_cannot(
    stack, monkeypatch, uncertain, expected
):
    client, _, services, _ = stack
    course_id, _ = prepare(stack)
    parent_id = client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"][0]["id"]
    session_id = focused_session(stack, course_id, parent_id)
    factory = stack[1]
    for index in range(2):
        _, state, _ = answer(stack, session_id, course_id, "a", index)
        continue_same_topic(stack, session_id, course_id, parent_id, state)
    original = services.generate

    def partial(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Assessment:
            result.coverage[0].score = 0.25
            result.uncertain = uncertain
            result.contradiction = True
        return result

    monkeypatch.setattr(services, "generate", partial)
    for index in range(2, 4):
        current, state, _ = answer(
            stack, session_id, course_id, "a", index, reasoning="An incomplete explanation"
        )
        if index < 3:
            client.post(
                f"/api/sessions/{session_id}/next",
                json={"expectedLearnerVersion": state["version"]},
            ).raise_for_status()
            assert work_once(factory, services)
    assert current["assessment"]["partial"]
    assert current["assessment"]["uncertain"] == uncertain
    assert current["assessment"]["confirmedWeakness"] == (not uncertain)
    assert state["overallStates"][parent_id] == expected
