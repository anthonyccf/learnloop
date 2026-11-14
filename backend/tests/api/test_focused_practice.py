from tests.release_fixtures import seed_legacy_release
import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from learnloop.core import domain
from learnloop.core.schemas import PlanChoice
from learnloop.persistence.database import Activity, Document, LearnerState
from learnloop.runtime.worker import work_once


def add_lesson(factory, document_id):
    with factory.begin() as db:
        doc = db.get(Document, document_id)
        graph = copy.deepcopy(doc.graph)
        original = graph["concepts"][0]
        id = document_id + ":learning-rate"
        graph["concepts"].append({**original, "id": id, "title": "Learning rate"})
        graph["resources"][id] = copy.deepcopy(graph["resources"][original["id"]])
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
        return original["id"], id


def test_lesson_practice_switches_to_requested_concept_and_next_stays_on_topic(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    original, target = add_lesson(factory, upload["documentId"])
    endpoint = f"/api/courses/{course_id}/sessions"
    session = client.post(endpoint, json={"expectedLearnerVersion": 0}).json()
    assert work_once(factory, services)
    before = client.get(f"/api/sessions/{session['id']}").json()
    old = before["activity"]
    assert old["conceptId"] == original
    selected = client.post(endpoint, json={"expectedLearnerVersion": 0, "conceptId": target})
    assert selected.status_code == 202
    assert selected.json()["id"] == session["id"] and selected.json()["targetConceptId"] == target
    duplicate = client.post(
        endpoint, json={"expectedLearnerVersion": 0, "conceptId": target}
    ).json()
    assert duplicate["runIds"] == selected.json()["runIds"]
    assert work_once(factory, services)
    focused = client.get(f"/api/sessions/{session['id']}").json()
    assert focused["activity"]["conceptId"] == target
    with factory() as db:
        assert db.get(Activity, old["id"]).status == "pending"
    assert (
        client.post(
            f"/api/activities/{old['id']}/responses",
            json={"operationId": str(uuid4()), "expectedLearnerVersion": 0, "choiceId": "a"},
        ).status_code
        == 409
    )
    assert client.post(f"/api/activities/{old['id']}/hint", json={}).status_code == 409
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0
    answer = client.post(
        f"/api/activities/{focused['activity']['id']}/responses",
        json={"operationId": str(uuid4()), "expectedLearnerVersion": 0, "choiceId": "a"},
    )
    assert answer.status_code == 202
    # Changing topics may not hide an answer that is currently being checked.
    assert (
        client.post(endpoint, json={"expectedLearnerVersion": 0, "conceptId": original}).status_code
        == 409
    )
    assert work_once(factory, services)
    assessed = client.get(f"/api/sessions/{session['id']}").json()
    assert assessed["activity"]["id"] == focused["activity"]["id"] and assessed["assessment"]
    version = client.get(f"/api/courses/{course_id}/learner-state").json()["version"]
    assert (
        client.post(
            f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": version}
        ).status_code
        == 202
    )
    assert work_once(factory, services)
    next_question = client.get(f"/api/sessions/{session['id']}").json()
    assert (
        next_question["activity"]["conceptId"] == target
        and next_question["activity"]["id"] != focused["activity"]["id"]
    )
    # Returning to the first topic restores its unanswered question.
    returned = client.post(
        endpoint, json={"expectedLearnerVersion": version, "conceptId": original}
    ).json()
    assert returned["activity"]["id"] == old["id"]


def test_queued_question_follows_the_lesson_the_learner_just_chose(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    original, target = add_lesson(factory, upload["documentId"])
    endpoint = f"/api/courses/{course_id}/sessions"
    session = client.post(
        endpoint, json={"expectedLearnerVersion": 0, "conceptId": original}
    ).json()
    switched = client.post(endpoint, json={"expectedLearnerVersion": 0, "conceptId": target})
    assert switched.status_code == 202
    body = switched.json()
    assert body["id"] == session["id"] and body["targetConceptId"] == target
    assert body["runIds"] == session["runIds"]
    assert work_once(factory, services)
    focused = client.get(f"/api/sessions/{session['id']}").json()
    assert focused["activity"]["conceptId"] == target


def test_completed_focused_topic_hands_next_topic_choice_to_tutor(stack, monkeypatch):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    original, target = add_lesson(factory, upload["documentId"])
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        graph["prerequisites"].append({"prerequisite": original, "dependent": target})
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    endpoint = f"/api/courses/{course_id}/sessions"
    session = client.post(
        endpoint, json={"expectedLearnerVersion": 0, "conceptId": original}
    ).json()
    assert work_once(factory, services)
    for version in range(2):
        current = client.get(f"/api/sessions/{session['id']}").json()
        assert current["activity"]["conceptId"] == original
        client.post(
            f"/api/activities/{current['activity']['id']}/responses",
            json={"operationId": str(uuid4()), "expectedLearnerVersion": version, "choiceId": "a"},
        ).raise_for_status()
        assert work_once(factory, services)
        state = client.get(f"/api/courses/{course_id}/learner-state").json()
        assert state["overallStates"][original] == (
            "developing" if version == 0 else "demonstrated"
        )
        # Assessment remains visible until the learner explicitly continues.
        assessed = client.get(f"/api/sessions/{session['id']}").json()
        assert assessed["activity"]["id"] == current["activity"]["id"]
        assert assessed["assessment"]
        client.post(
            f"/api/sessions/{session['id']}/next",
            json={"expectedLearnerVersion": state["version"]},
        ).raise_for_status()
        if version == 0:
            assert work_once(factory, services)
    offered = []
    generate = services.generate

    def choose(role, instruction, context, output):
        if output is PlanChoice:
            offered.extend(context["candidates"])
        return generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", choose)
    assert work_once(factory, services)
    continued = client.get(f"/api/sessions/{session['id']}").json()
    assert continued["targetConceptId"] is None
    assert continued["activity"]["conceptId"] == target
    assert [c["conceptId"] for c in offered] == [target]
    # Completing the last available topic ends with a notice, without looping
    # over already demonstrated topics or leaving the modal in a loading state.
    for version in range(2, 4):
        current = client.get(f"/api/sessions/{session['id']}").json()
        client.post(
            f"/api/activities/{current['activity']['id']}/responses",
            json={"operationId": str(uuid4()), "expectedLearnerVersion": version, "choiceId": "a"},
        ).raise_for_status()
        assert work_once(factory, services)
        client.post(
            f"/api/sessions/{session['id']}/next",
            json={"expectedLearnerVersion": version + 1},
        ).raise_for_status()
        assert work_once(factory, services)
    finished = client.get(f"/api/sessions/{session['id']}").json()
    assert finished["activity"] is None and finished["notice"]


def test_direct_quiz_blocks_until_prerequisite_is_demonstrated(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    original, target = add_lesson(factory, upload["documentId"])
    endpoint = f"/api/courses/{course_id}/sessions"
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        graph["prerequisites"].append({"prerequisite": original, "dependent": target})
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    target_request = {"expectedLearnerVersion": 0, "conceptId": target}
    blocked = client.post(endpoint, json=target_request)
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "unmet_prerequisites"
    assert detail["requested"]["conceptId"] == target
    assert [p["conceptId"] for p in detail["prerequisites"]] == [original]
    assert detail["nextStep"]["conceptId"] == original
    assert not work_once(factory, services)
    session = client.post(endpoint, json={"expectedLearnerVersion": 0, "conceptId": original}).json()
    assert work_once(factory, services)
    session_url = f"/api/sessions/{session['id']}"
    before = client.get(session_url).json()
    assert (
        client.post(
            endpoint, json={"expectedLearnerVersion": 0, "conceptId": "other-course:unknown"}
        ).status_code
        == 404
    )
    assert client.post(endpoint, json=target_request).status_code == 409
    assert client.get(session_url).json() == before
    client.post(f"/api/activities/{before['activity']['id']}/hint", json={}).raise_for_status()
    for version in range(3):
        activity = client.get(session_url).json()["activity"]
        assert activity["conceptId"] == original
        client.post(
            f"/api/activities/{activity['id']}/responses",
            json={"operationId": str(uuid4()), "expectedLearnerVersion": version, "choiceId": "a"},
        ).raise_for_status()
        assert work_once(factory, services)
        direct = client.post(endpoint, json={**target_request, "expectedLearnerVersion": version + 1})
        if version < 2:
            assert direct.status_code == 409
            client.post(f"{session_url}/next", json={"expectedLearnerVersion": version + 1}).raise_for_status()
            assert work_once(factory, services)
        else:
            assert direct.status_code == 202
    assert work_once(factory, services)
    assert client.get(session_url).json()["activity"]["conceptId"] == target


def test_block_recommends_eligible_ancestor_and_checks_required_difficulty():
    concepts = [
        {"id": id, "title": title, "targetDifficulty": difficulty}
        for id, title, difficulty in (
            ("a", "Foundation", "intermediate"), ("b", "Application", "intermediate"),
            ("c", "Synthesis", "advanced"),
        )
    ]
    graph = {"concepts": concepts, "prerequisites": [
        {"prerequisite": "a", "dependent": "b"}, {"prerequisite": "b", "dependent": "c"},
    ]}
    evidence = {"a": {"basic": {"state": "demonstrated"}}}
    blocked = domain.prerequisite_block(graph, evidence, "c")
    assert blocked["prerequisites"][0]["conceptId"] == "b"
    assert blocked["nextStep"] == {
        "conceptId": "a", "title": "Foundation", "difficulty": "intermediate", "state": "unassessed",
    }
    assert domain.prerequisite_block(graph, evidence, "b")


@pytest.mark.parametrize("expire_during_generation", [True, False])
def test_quiz_rechecks_expired_prerequisites_without_discarding_an_assigned_question(
    stack, monkeypatch, expire_during_generation
):
    from tests.api.test_integration import prepare

    class Clock(datetime):
        current = datetime.now(UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(domain, "datetime", Clock)
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    original, target = add_lesson(factory, upload["documentId"])
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        graph["prerequisites"].append({"prerequisite": original, "dependent": target})
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id))
        state.evidence = {original: {"basic": {
            "state": "demonstrated", "reviewAt": (Clock.current + timedelta(hours=1)).isoformat(),
        }}}

    generate = services.generate

    def expire_review(role, instruction, context, output):
        if expire_during_generation and output is PlanChoice:
            Clock.current += timedelta(hours=2)
        return generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", expire_review)
    launch = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0, "conceptId": target}
    )
    assert launch.status_code == 202
    assert work_once(factory, services)
    session_url = f"/api/sessions/{launch.json()['id']}"
    session = client.get(session_url).json()
    if expire_during_generation:
        assert session["activity"] is None
        assert session["prerequisiteBlock"]["nextStep"]["state"] == "review_due"
        assert session["prerequisiteBlock"]["nextStep"]["conceptId"] == original
        return

    Clock.current += timedelta(hours=2)
    activity = session["activity"]
    assert activity["conceptId"] == target
    resumed = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0, "conceptId": target}
    )
    assert resumed.status_code == 202 and resumed.json()["activity"] == activity
    client.post(
        f"/api/activities/{activity['id']}/responses",
        json={"operationId": str(uuid4()), "expectedLearnerVersion": 0, "choiceId": "a"},
    ).raise_for_status()
    assert work_once(factory, services)
    blocked = client.post(f"{session_url}/next", json={"expectedLearnerVersion": 1})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["nextStep"]["state"] == "review_due"
    assert client.get(session_url).json()["activity"]["status"] == "assessed"
