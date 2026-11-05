from tests.release_fixtures import seed_legacy_release
import copy
from uuid import uuid4

from learnloop.core.schemas import PlanChoice
from learnloop.persistence.database import Activity, Document
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


def test_direct_challenge_allows_unmet_prerequisites_and_rejects_unknown_lessons(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    original, target = add_lesson(factory, upload["documentId"])
    endpoint = f"/api/courses/{course_id}/sessions"
    session = client.post(endpoint, json={"expectedLearnerVersion": 0}).json()
    assert work_once(factory, services)
    before = client.get(f"/api/sessions/{session['id']}").json()
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        graph["prerequisites"].append({"prerequisite": original, "dependent": target})
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    assert (
        client.post(
            endpoint, json={"expectedLearnerVersion": 0, "conceptId": "other-course:unknown"}
        ).status_code
        == 404
    )
    assert client.get(f"/api/sessions/{session['id']}").json()["activity"] == before["activity"]
    selected = client.post(endpoint, json={"expectedLearnerVersion": 0, "conceptId": target})
    assert selected.status_code == 202
    assert work_once(factory, services)
    focused = client.get(f"/api/sessions/{session['id']}").json()
    assert focused["activity"]["conceptId"] == target
    # Attempting a challenge does not manufacture prerequisite evidence.
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0
    response = client.post(
        f"/api/activities/{focused['activity']['id']}/responses",
        json={"operationId": str(uuid4()), "expectedLearnerVersion": 0, "choiceId": "a"},
    )
    assert response.status_code == 202
    assert work_once(factory, services)
    version = client.get(f"/api/courses/{course_id}/learner-state").json()["version"]
    assert (
        client.post(
            f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": version}
        ).status_code
        == 202
    )
    assert work_once(factory, services)
    assert client.get(f"/api/sessions/{session['id']}").json()["activity"]["conceptId"] == target
