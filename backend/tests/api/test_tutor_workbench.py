"""The workbench uses production agents without touching a real learner."""

import pytest
from sqlalchemy import select

from learnloop.api.routes import workbench_tutor
from learnloop.core.schemas import TutorObservation, WorkbenchDecision, WorkbenchTutorReply
from learnloop.persistence.database import Activity, LearnerState, StudySession, WorkbenchMemory
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare


@pytest.mark.parametrize("question_format,answer,expected", [
    ("multiple_answer", {"choiceIds": ["b", "a"]}, {"choiceIds": ["a", "b"]}),
    ("fill_in", {"blanks": [{"id": "term", "text": "gradient"}]}, {"blanks": {"term": "gradient"}}),
    ("open", {"answerText": "An explanation."}, {"answerText": "An explanation."}),
])
def test_workbench_accepts_and_restores_typed_answers(stack, question_format, answer, expected):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Mixed"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    assert client.post(path + "/start", json={"mode": "quiz"}).status_code == 202
    assert work_once(factory, services)
    quiz = client.get(path).json()
    with factory.begin() as db:
        activity = db.get(Activity, quiz["activity"]["id"])
        activity.public = {**activity.public, "format": question_format, "blankIds": ["term"]}
    body = {"operationId": "typed-answer", "expectedLearnerVersion": quiz["version"], **answer}
    response = client.post(path + "/answer", json=body)
    assert response.status_code == 202, response.text
    assert response.json()["answer"] == expected
    assert client.post(path + "/answer", json=body).status_code == 202


def test_assessment_retry_correct_incorrect_and_pinned_release(stack, monkeypatch):
    from learnloop.core.errors import ServiceError
    from learnloop.core.schemas import Assessment

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    old = client.get(f"/api/courses/{course_id}").json()
    base = f"/api/workbench/courses/{course_id}/memories"
    first = client.post(base, json={"name": "Correct"}).json()["id"]
    second = client.post(base, json={"name": "Incorrect"}).json()["id"]
    paths = [f"/api/workbench/memories/{id}" for id in (first, second)]
    for path in paths:
        assert client.post(path + "/start", json={"mode": "quiz"}).status_code == 202
        assert work_once(factory, services)
    topic = old["graph"]["topics"][0]
    root = {"id": "evaluation-root", "title": "Evaluation group", "summary": "A group for testing course release changes.", "parentId": None, "conceptIds": []}
    published = client.post(f"/api/courses/{course_id}/hierarchy", json={"expectedReleaseId": old["release"]["id"], "topics": [root, {**topic, "parentId": root["id"]}]})
    assert published.status_code == 200, published.text
    assert client.get(f"/api/courses/{course_id}").json()["release"]["id"] != old["release"]["id"]
    for index, path in enumerate(paths):
        quiz = client.get(path).json()
        with factory() as db:
            correct = db.get(Activity, quiz["activity"]["id"]).private["correctChoiceId"]
        choice = correct if index == 0 else next(c["id"] for c in quiz["activity"]["choices"] if c["id"] != correct)
        body = {"operationId": f"evaluation-{index}", "expectedLearnerVersion": quiz["version"], "choiceId": choice}
        response = client.post(path + "/answer", json=body)
        assert response.status_code == 202
        queued = response.json()["handoffs"][-1]
        assert queued["request"]["courseReleaseId"] == old["release"]["id"]
        assert queued["request"]["parentRunId"] == quiz["runs"][0]["id"]
        if index == 1:
            original = services.generate
            failed = False
            def fail_once(role, instruction, context, output):
                nonlocal failed
                if output is Assessment and not failed:
                    failed = True
                    raise ServiceError("temporary_error", "Temporary assessment failure.", True)
                return original(role, instruction, context, output)
            monkeypatch.setattr(services, "generate", fail_once)
            assert work_once(factory, services)
            interrupted = client.get(path).json()
            assert interrupted["handoffs"][-1]["status"] == "failed"
            assert interrupted["handoffs"][-1]["retryable"]
            assert interrupted["version"] == 0 and interrupted["assessment"] is None
            assert client.post(path + "/retry", json={}).status_code == 200
        assert work_once(factory, services)
        assessed = client.get(path).json()
        assert assessed["assessment"]["correct"] is (index == 0)
        assert assessed["version"] == 1 and len(assessed["history"]) == 1
        assert assessed["handoffs"][-1]["status"] == "completed"
        assert assessed["handoffs"][-1]["runId"] == queued["runId"]
        assert client.post(path + "/answer", json=body).status_code == 202
        assert client.get(path).json()["version"] == 1
    assert client.get(paths[0]).json()["evidence"] != client.get(paths[1]).json()["evidence"]


def test_missing_lesson_requests_expert_and_keeps_course_unchanged(stack, monkeypatch):
    from learnloop.agents.tutoring import workbench

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    course_before = client.get(f"/api/courses/{course_id}").json()
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Lesson handoff"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    monkeypatch.setattr(workbench_tutor, "lesson_for", lambda *args: None)
    monkeypatch.setattr(workbench, "lesson_for", lambda *args: None)
    started = client.post(path + "/start", json={"mode": "lesson"})
    assert started.status_code == 202 and started.json()["lesson"] is None
    assert work_once(factory, services)
    view = client.get(path).json()
    assert view["lesson"] and view["lesson"]["sources"]
    handoff = view["handoffs"][0]
    assert handoff["status"] == "completed" and handoff["request"]["task"] == "generate_lesson"
    assert handoff["request"]["conceptId"] == view["lesson"]["conceptId"]
    assert handoff["request"]["courseReleaseId"] == course_before["release"]["id"]
    assert client.get(f"/api/courses/{course_id}").json()["release"] == course_before["release"]


def test_missing_auto_lesson_without_sources_reports_failure(stack, monkeypatch):
    from learnloop.agents.tutoring import workbench

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Lesson missing sources"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    monkeypatch.setattr(workbench, "lesson_for", lambda *args: None)
    monkeypatch.setattr(workbench, "retrieve", lambda *args, **kwargs: [])
    assert client.post(path + "/start", json={"mode": "auto"}).status_code == 202
    assert work_once(factory, services)
    view = client.get(path).json()
    assert view["lesson"] is None and view["handoffs"][0]["status"] == "failed"
    assert "No published passages" in view["handoffs"][0]["summary"]


def test_expert_lesson_rejects_unsupported_content(stack, monkeypatch):
    from learnloop.agents.tutoring import workbench

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Unsupported lesson"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    monkeypatch.setattr(workbench_tutor, "lesson_for", lambda *args: None)
    monkeypatch.setattr(workbench, "lesson_for", lambda *args: None)
    services.grounding_status = "unsupported"
    assert client.post(path + "/start", json={"mode": "lesson"}).status_code == 202
    assert work_once(factory, services)
    view = client.get(path).json()
    assert view["lesson"] is None and view["handoffs"][0]["status"] == "failed"
    assert "did not establish support" in view["handoffs"][0]["summary"]


def test_missing_question_handoff_generates_and_hides_private_answer(stack, monkeypatch):
    from learnloop.agents.tutoring import agent as tutor
    from learnloop.core.errors import ServiceError

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Expert handoff"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    monkeypatch.setattr(tutor, "prepared_question", lambda *args, **kwargs: (None, []))
    monkeypatch.setattr(tutor, "saved_question", lambda *args, **kwargs: (None, [], None))
    original_generate = tutor.generate_question
    failed = False
    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise ServiceError("temporary_expert_error", "Temporary Expert failure.", True)
        return original_generate(*args, **kwargs)
    monkeypatch.setattr(tutor, "generate_question", fail_once)
    old = client.get(f"/api/courses/{course_id}").json()
    assert client.post(path + "/start", json={"mode": "quiz"}).status_code == 202
    topic = old["graph"]["topics"][0]
    root = {"id": "expert-eval-root", "title": "Expert evaluation", "summary": "A group for testing the pinned release.", "parentId": None, "conceptIds": []}
    assert client.post(f"/api/courses/{course_id}/hierarchy", json={"expectedReleaseId": old["release"]["id"], "topics": [root, {**topic, "parentId": root["id"]}]}).status_code == 200
    assert work_once(factory, services)
    interrupted = client.get(path).json()
    assert interrupted["handoffs"][0]["status"] == "failed" and interrupted["handoffs"][0]["retryable"]
    request_id = interrupted["handoffs"][0]["request"]["requestId"]
    assert client.post(path + "/retry", json={}).status_code == 200
    assert work_once(factory, services)
    view = client.get(path).json()
    assert view["activity"] and view["activity"]["status"] == "pending"
    handoff = view["handoffs"][0]
    assert handoff["request"]["targetAgent"] == "expert"
    assert handoff["request"]["requestId"] == request_id
    assert handoff["request"]["courseReleaseId"] == old["release"]["id"]
    assert handoff["request"]["conceptId"] == view["activity"]["conceptId"]
    assert handoff["status"] == "completed" and handoff["result"]["sourceCount"] > 0
    assert "correctChoiceId" not in str(view)


def test_missing_question_handoff_reports_missing_sources(stack, monkeypatch):
    from learnloop.agents.tutoring import agent as tutor

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Missing sources"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    monkeypatch.setattr(tutor, "prepared_question", lambda *args, **kwargs: (None, []))
    monkeypatch.setattr(tutor, "saved_question", lambda *args, **kwargs: (None, [], None))
    monkeypatch.setattr(tutor, "retrieve", lambda *args, **kwargs: [])
    assert client.post(path + "/start", json={"mode": "quiz"}).status_code == 202
    assert work_once(factory, services)
    view = client.get(path).json()
    assert view["activity"] is None
    assert view["handoffs"][0]["status"] == "failed"
    assert "No published passages" in view["handoffs"][0]["summary"]


def test_workbench_lesson_quiz_assessment_and_isolation(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    before = client.get(f"/api/courses/{course_id}/learner-state").json()
    base = f"/api/workbench/courses/{course_id}/memories"
    first = client.post(base, json={"name": "Learner A"}).json()
    second = client.post(base, json={"name": "Learner B"}).json()
    path = f"/api/workbench/memories/{first['id']}"
    fresh = client.get(path).json()
    assert fresh["graph"]["concepts"]
    assert all(set(levels) == {"basic", "intermediate", "advanced"} and set(levels.values()) == {"unassessed"} for levels in fresh["evidenceStates"].values())

    lesson = client.post(path + "/start", json={"request": "Help me understand gradient descent", "mode": "lesson"})
    assert lesson.status_code == 202, lesson.text
    assert lesson.json()["lesson"]["lesson"]["explanation"]
    assert client.get(path).json()["lesson"] == lesson.json()["lesson"]

    quiz = client.post(path + "/start", json={"request": "Practice gradient descent", "mode": "quiz"})
    assert quiz.status_code == 202, quiz.text
    assert work_once(factory, services)
    quiz = client.get(path).json()
    assert quiz["activity"] and quiz["activity"]["status"] == "pending", quiz
    assert "correctChoiceId" not in str(quiz["activity"])
    assert client.get(f"/api/courses/{course_id}/runs").json()[-1]["workflow"] == "course_preparation"
    assert client.post(f"/api/activities/{quiz['activity']['id']}/hint").status_code == 404
    assert client.post(path + "/start", json={"request": "Quiz", "mode": "quiz"}).status_code == 409
    with factory() as db:
        correct = db.get(Activity, quiz["activity"]["id"]).private["correctChoiceId"]
    answer = {"operationId": "sandbox-answer", "expectedLearnerVersion": quiz["version"], "choiceId": correct}
    queued = client.post(path + "/answer", json=answer)
    assert queued.status_code == 202
    handoff = queued.json()["handoffs"][0]
    assert handoff["status"] == "queued" and handoff["result"] is None
    assert handoff["request"]["requestId"] == answer["operationId"]
    assert handoff["request"]["parentRunId"] == quiz["runs"][0]["id"]
    assert handoff["request"]["sessionId"] == quiz["sessionId"]
    assert handoff["request"]["conceptId"] == quiz["activity"]["conceptId"]
    assert handoff["request"]["targetAgent"] == "assessing"
    duplicate = client.post(path + "/answer", json=answer)
    assert duplicate.status_code == 202 and len(duplicate.json()["handoffs"]) == 1
    assert client.post(path + "/clear", json={"sessionId": quiz["sessionId"], "stepId": quiz["stepId"]}).status_code == 409
    assert work_once(factory, services)
    reviewed = client.get(path).json()
    assert reviewed["assessment"] and reviewed["version"] == 1, reviewed
    completed = reviewed["handoffs"][0]
    assert completed["runId"] == handoff["runId"] and completed["status"] == "completed"
    assert completed["result"]["assessmentId"] == reviewed["assessment"]["assessmentId"]
    assert completed["result"]["learnerVersion"] == reviewed["version"]
    assert reviewed["evidence"]
    concept_id = reviewed["activity"]["conceptId"]
    level = reviewed["activity"]["difficulty"]
    assert reviewed["evidenceStates"][concept_id][level] == reviewed["evidence"][concept_id][level]["state"]
    assert any(concept["id"] == concept_id for concept in reviewed["graph"]["concepts"])
    assert len(reviewed["history"]) == 1
    original_generate = services.generate
    planning_contexts = []

    def capture(role, instruction, context, output):
        if output.__name__ == "PlanChoice":
            planning_contexts.append(context)
        return original_generate(role, instruction, context, output)

    services.generate = capture
    original_candidates = workbench_tutor.candidates
    selection_contexts = []

    def capture_candidates(graph, evidence, *args, **kwargs):
        selection_contexts.append((evidence, kwargs.get("memory")))
        return original_candidates(graph, evidence, *args, **kwargs)

    monkeypatch.setattr(workbench_tutor, "candidates", capture_candidates)
    next_quiz = client.post(path + "/start", json={"mode": "quiz"})
    assert next_quiz.status_code == 202, next_quiz.text
    assert selection_contexts and selection_contexts[0][0] and selection_contexts[0][1]
    session_id = next_quiz.json()["sessionId"]
    assert client.post(path + "/clear", json={"sessionId": session_id, "stepId": next_quiz.json()["stepId"]}).status_code == 409
    assert work_once(factory, services)
    assert planning_contexts and planning_contexts[0]["learnerMemory"]
    assert any(candidate["evidenceIds"] for candidate in planning_contexts[0]["candidates"])
    pending = client.get(path).json()
    assert pending["activity"]["status"] == "pending"
    assert client.post(path + "/clear", json={"sessionId": "stale-session"}).status_code == 409
    cleared = client.post(path + "/clear", json={"sessionId": session_id, "stepId": pending["stepId"]})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["sessionId"] is None and cleared.json()["activity"] is None
    assert cleared.json()["version"] == reviewed["version"]
    assert cleared.json()["evidence"] == reviewed["evidence"]
    assert cleared.json()["history"] == reviewed["history"]
    with factory() as db:
        assert db.get(Activity, pending["activity"]["id"]).status == "skipped"
        assert db.get(StudySession, session_id).status == "ended"
    restarted = client.post(path + "/start", json={"mode": "auto"})
    assert restarted.status_code == 202
    assert work_once(factory, services)
    assert client.get(path).json()["branch"] == "lesson"
    assert restarted.json()["evidence"] == reviewed["evidence"]
    other = client.get(f"/api/workbench/memories/{second['id']}").json()
    assert other["version"] == 0 and other["evidence"] == {}
    assert other["evidenceStates"][concept_id][level] == "unassessed"
    assert client.get(f"/api/courses/{course_id}/learner-state").json() == before
    with factory() as db:
        rows = list(db.scalars(select(LearnerState).where(LearnerState.course_id == course_id)))
        assert {state.owner_id for state in rows} >= {"test-owner", "workbench:" + first["id"], "workbench:" + second["id"]}
        assert db.get(WorkbenchMemory, first["id"]).owner_id == "test-owner"


def test_auto_routing_and_optional_request(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Auto"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    result = client.post(path + "/start", json={"request": "Explain gradient descent", "mode": "auto"})
    assert result.status_code == 202
    assert work_once(factory, services)
    assert client.get(path).json()["branch"] == "lesson"
    lesson = client.post(path + "/start", json={"mode": "auto"})
    assert lesson.status_code == 202, lesson.text
    assert work_once(factory, services)
    assert client.get(path).json()["branch"] == "lesson" and lesson.json()["request"] == ""
    quiz = client.post(path + "/start", json={"request": "  ", "mode": "quiz"})
    assert quiz.status_code == 202, quiz.text
    assert quiz.json()["branch"] == "quiz" and quiz.json()["request"] == ""
    assert work_once(factory, services)
    assert client.get(path).json()["activity"]


def test_brain_map_reports_effective_status_at_each_level(stack):
    client, factory, _, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Review"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    concept = client.get(path).json()["graph"]["concepts"][0]
    with factory.begin() as db:
        state = db.scalar(select(LearnerState).where(LearnerState.owner_id == "workbench:" + memory_id))
        state.evidence = {concept["id"]: {"basic": {"state": "demonstrated", "reviewAt": "2020-01-01T00:00:00+00:00"}, "intermediate": {"state": "developing"}}}
    view = client.get(path).json()
    assert view["evidenceStates"][concept["id"]] == {"basic": "review_due", "intermediate": "developing", "advanced": "unassessed"}
    assert view["evidence"][concept["id"]]["basic"]["state"] == "demonstrated"


def test_hierarchy_publish_keeps_concepts_memory_and_pinned_session(stack):
    client, _, _, _ = stack
    course_id, _ = prepare(stack)
    course = client.get(f"/api/courses/{course_id}").json()
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Pinned"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    assert client.post(path + "/start", json={"mode": "lesson"}).status_code == 202
    before = client.get(path).json()
    old_topic = course["graph"]["topics"][0]
    root = {"id": "new-root", "title": "New group", "summary": "A group for the published course.", "parentId": None, "conceptIds": []}
    topics = [root, {**old_topic, "parentId": "new-root"}]
    url = f"/api/courses/{course_id}/hierarchy"
    result = client.post(url, json={"expectedReleaseId": course["release"]["id"], "topics": topics})
    assert result.status_code == 200, result.text
    updated = client.get(f"/api/courses/{course_id}").json()
    assert updated["release"]["version"] == course["release"]["version"] + 1
    assert [c["id"] for c in updated["graph"]["concepts"]] == [c["id"] for c in course["graph"]["concepts"]]
    assert updated["graph"]["topics"][1]["parentId"] == "new-root"
    pinned = client.get(path).json()
    assert pinned["graph"] == before["graph"] and pinned["evidence"] == before["evidence"]
    assert pinned["courseGraph"]["topics"] == updated["graph"]["topics"]
    assert len(pinned["courseGraph"]["concepts"]) == len(updated["graph"]["concepts"])
    assert client.post(url, json={"expectedReleaseId": course["release"]["id"], "topics": topics}).status_code == 409
    bad = [{**root, "parentId": old_topic["id"]}, topics[1]]
    assert client.post(url, json={"expectedReleaseId": updated["release"]["id"], "topics": bad}).status_code == 409
    assert client.get(f"/api/courses/{course_id}").json()["release"] == updated["release"]


def test_tutor_template_applies_to_sandbox_planning(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Configured"}).json()["id"]
    original = services.generate
    calls = []

    def capture(role, instruction, context, output, **kwargs):
        calls.append((role, instruction, output.__name__, kwargs))
        return original(role, instruction, context, output)

    services.generate = capture
    template = {"id": "t1", "agent": "tutor", "name": "Experiment", "prompts": {"analysis": "Focus on prior knowledge.", "lesson": "Unused lesson.", "questions": "Unused question."}, "enabledTools": [], "model": "configured", "temperature": 0.4}
    response = client.post(f"/api/workbench/memories/{memory_id}/start", json={"request": "Quiz me", "mode": "quiz", "promptTemplate": template})
    assert response.status_code == 202, response.text
    assert work_once(factory, services)
    state = client.get(f"/api/workbench/memories/{memory_id}").json()
    assert state["activity"], state
    planning = next(call for call in calls if call[2] == "PlanChoice")
    assert "Focus on prior knowledge." in planning[1]
    assert planning[3]["temperature"] == 0.4
    chat = client.post(f"/api/workbench/memories/{memory_id}/chat", json={"sessionId": state["sessionId"], "stepId": state["stepId"], "operationId": "configured-chat", "message": "Please explain the concept."})
    assert chat.status_code == 200, chat.text
    response_call = next(call for call in calls if call[2] == "WorkbenchTutorReply")
    assert "Unused lesson." in response_call[1]
    assert response_call[3]["temperature"] == 0.4


def test_chat_in_lesson_does_not_create_assessed_evidence(stack):
    client, _, _, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Lesson chat"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    lesson = client.post(path + "/start", json={"mode": "lesson"}).json()
    result = client.post(path + "/chat", json={"sessionId": lesson["sessionId"], "stepId": lesson["stepId"], "operationId": "lesson-chat", "message": "I already know calculus."})
    assert result.status_code == 200, result.text
    assert result.json()["lesson"] and result.json()["activity"] is None
    assert result.json()["version"] == 0 and result.json()["evidence"] == {}
    assert result.json()["chat"][-1]["role"] == "assistant"


def test_chat_preserves_quiz_and_uses_memory_for_next_activity(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Chat learner"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    initial = client.post(path + "/start", json={"mode": "quiz"}).json()
    assert work_once(factory, services)
    pending = client.get(path).json()
    message = {"sessionId": initial["sessionId"], "stepId": initial["stepId"], "operationId": "chat-1", "message": "I confuse the direction"}
    services.fail_next = True
    assert client.post(path + "/chat", json=message).status_code == 503
    with factory() as db:
        assert db.get(Activity, pending["activity"]["id"]).hinted is False
    original_generate = services.generate
    contexts = []

    def respond(role, instruction, context, output):
        if output is WorkbenchTutorReply:
            contexts.append(context)
            assert "correctChoiceId" not in str(context)
            return WorkbenchTutorReply(text="Think about the update direction.", observation=TutorObservation(kind="gap", summary="Uncertain about update direction.", quote="I confuse the direction"), nextAction="lesson")
        if output is WorkbenchDecision:
            assert context["conversation"][-2]["text"] == "I confuse the direction"
            assert context["previousActivity"]["kind"] == "quiz"
            assert context["previousActivity"]["assessment"]["hinted"] is True
            return WorkbenchDecision(action="lesson", reason="The learner needs an explanation first.")
        return original_generate(role, instruction, context, output)

    services.generate = respond
    result = client.post(path + "/chat", json=message)
    assert result.status_code == 200, result.text
    after = result.json()
    assert after["activity"]["id"] == pending["activity"]["id"] and after["activity"]["status"] == "pending"
    assert after["activity"]["hintUsed"] is True and after["version"] == 0
    assert after["chat"][-1]["nextAction"] == "lesson"
    assert client.post(path + "/chat", json=message).status_code == 200
    assert len(contexts) == 1
    assert client.post(path + "/chat", json={**message, "message": "Different"}).status_code == 409
    with factory() as db:
        activity = db.get(Activity, pending["activity"]["id"])
        assert len(activity.private["tutorObservations"]) == 1
        correct = activity.private["correctChoiceId"]
    assert client.post(path + "/answer", json={"operationId": "answer-chat", "expectedLearnerVersion": 0, "choiceId": correct}).status_code == 202
    assert work_once(factory, services)
    assessed = client.get(path).json()
    assert assessed["assessment"]["hinted"] is True
    continued = client.post(path + "/start", json={"mode": "auto", "continuation": True, "stepId": assessed["stepId"]})
    assert continued.status_code == 202 and continued.json()["sessionId"] == initial["sessionId"]
    assert work_once(factory, services)
    next_step = client.get(path).json()
    assert next_step["branch"] == "lesson" and next_step["lesson"]
    assert next_step["chat"][-1]["text"] == "Think about the update direction."
    assert next_step["statistics"]["sessions"] == 1
    assert client.post(path + "/clear", json={"sessionId": initial["sessionId"], "stepId": initial["stepId"]}).status_code == 409
    assert client.post(path + "/chat", json=message).status_code == 409


def test_auto_routing_and_provider_reported_load_statistics(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Metrics learner"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    original_generate = services.generate

    def measured(role, instruction, context, output):
        services.last_generation_usage = {"inputTokens": 100, "outputTokens": 25, "costUsd": 0.0125}
        if output is WorkbenchDecision:
            return WorkbenchDecision(action="quiz", reason="Practice matches the learner's current need.")
        return original_generate(role, instruction, context, output)

    services.generate = measured
    initial = client.post(path + "/start", json={"mode": "auto", "request": "Check my understanding"})
    assert initial.status_code == 202
    assert work_once(factory, services)
    result = client.get(path).json()
    assert result["branch"] == "quiz" and result["activity"]
    stats = result["statistics"]
    assert stats["sessions"] == 1 and stats["loadDurationMs"] >= 0
    assert stats["loadUsage"]["calls"] >= 1
    assert stats["loadUsage"]["inputTokens"] == stats["loadUsage"]["calls"] * 100
    assert stats["loadUsage"]["costUsd"] == stats["loadUsage"]["calls"] * 0.0125


def test_continue_after_lesson_avoids_repeating_same_lesson(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Lesson progression"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    initial = client.post(path + "/start", json={"mode": "lesson"})
    assert initial.status_code == 202
    shown = initial.json()
    assert shown["lesson"]
    original = services.generate

    def choose_lesson(role, instruction, context, output):
        if output is WorkbenchDecision:
            return WorkbenchDecision(action="lesson", reason="Review the same explanation.")
        return original(role, instruction, context, output)

    services.generate = choose_lesson
    continued = client.post(path + "/start", json={"mode": "auto", "continuation": True, "stepId": shown["stepId"]})
    assert continued.status_code == 202, continued.text
    assert work_once(factory, services)
    result = client.get(path).json()
    assert result["branch"] == "quiz"
    assert result["activity"] and result["activity"]["conceptId"] == shown["lesson"]["conceptId"]
    assert result["lesson"] is None


def test_continue_from_blocked_lesson_selects_prerequisite(stack, monkeypatch):
    client, _, _, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Blocked lesson"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    shown = client.post(path + "/start", json={"mode": "lesson"}).json()
    old_id = shown["lesson"]["conceptId"]
    original_graph = workbench_tutor.course_graph

    def graph_with_prerequisite(*args):
        graph = original_graph(*args)
        graph["concepts"].append({**graph["concepts"][0], "id": "prerequisite", "title": "Required topic"})
        return graph

    monkeypatch.setattr(workbench_tutor, "course_graph", graph_with_prerequisite)
    monkeypatch.setattr(workbench_tutor, "prerequisite_block", lambda graph, evidence, concept_id:
                        {"nextStep": {"conceptId": "prerequisite"}} if concept_id == old_id else None)
    result = client.post(path + "/start", json={"mode": "auto", "continuation": True, "stepId": shown["stepId"]})
    assert result.status_code == 202, result.text
    assert result.json()["runs"][0]["conceptId"] == "prerequisite"


def test_stale_chat_does_not_modify_the_pending_question(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Concurrent"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    started = client.post(path + "/start", json={"mode": "quiz"}).json()
    assert work_once(factory, services)
    activity_id = client.get(path).json()["activity"]["id"]
    original_generate = services.generate

    def respond(role, instruction, context, output):
        if output is WorkbenchTutorReply:
            with factory.begin() as db:
                memory = db.get(WorkbenchMemory, memory_id)
                memory.data = {**memory.data, "chat": [{"role": "user", "text": "Another message"}]}
            return WorkbenchTutorReply(text="Consider the update.", observation=None, nextAction="none")
        return original_generate(role, instruction, context, output)

    services.generate = respond
    response = client.post(path + "/chat", json={"sessionId": started["sessionId"], "stepId": started["stepId"], "operationId": "stale-chat", "message": "Please explain"})
    assert response.status_code == 409
    with factory() as db:
        assert db.get(Activity, activity_id).hinted is False


def test_continuation_advances_after_target_is_demonstrated(stack, monkeypatch):
    from learnloop.core.domain import target_difficulty

    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Progression"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    assert client.post(path + "/start", json={"mode": "quiz"}).status_code == 202
    assert work_once(factory, services)
    pending = client.get(path).json()
    with factory() as db:
        answer = db.get(Activity, pending["activity"]["id"]).private["correctChoiceId"]
    assert client.post(path + "/answer", json={"operationId": "progress-answer", "expectedLearnerVersion": pending["version"], "choiceId": answer}).status_code == 202
    assert work_once(factory, services)
    assessed = client.get(path).json()
    original_graph = workbench_tutor.course_graph
    with factory.begin() as db:
        graph = original_graph(db, course_id, db.get(StudySession, assessed["sessionId"]).release_id)
        concept = next(c for c in graph["concepts"] if c["id"] == assessed["activity"]["conceptId"])
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id, LearnerState.owner_id == f"workbench:{memory_id}"))
        state.evidence = {**state.evidence, concept["id"]: {**state.evidence.get(concept["id"], {}), target_difficulty(concept): {"state": "demonstrated"}}}
    no_next = client.post(path + "/start", json={"mode": "auto", "continuation": True, "stepId": assessed["stepId"]})
    assert no_next.status_code == 409
    assert "No eligible topic" in str(no_next.json())
    assert client.get(path).json()["stepId"] == assessed["stepId"]

    def graph_with_next(*args):
        graph = original_graph(*args)
        graph["concepts"].append({**graph["concepts"][0], "id": "next-concept", "title": "Next topic"})
        return graph

    monkeypatch.setattr(workbench_tutor, "course_graph", graph_with_next)
    continued = client.post(path + "/start", json={"mode": "auto", "continuation": True, "stepId": assessed["stepId"]})
    assert continued.status_code == 202, continued.text
    assert continued.json()["sessionId"] == assessed["sessionId"]
    assert continued.json()["runs"][0]["conceptId"] == "next-concept"


def test_pre_assessment_course_concepts_and_lesson(stack, monkeypatch):
    from learnloop.agents.tutoring import agent as tutor_agent

    monkeypatch.setattr(tutor_agent, "select_question_format", lambda *args: "single_answer")
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Baseline"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    response = client.post(path + "/start", json={"mode": "pre_assessment"})
    assert response.status_code == 202, response.text
    total = len(response.json()["graph"]["concepts"])
    assert response.json()["preAssessment"]["total"] == total
    for index in range(total):
        assert work_once(factory, services)
        quiz = client.get(path).json()
        assert quiz["preAssessment"]["completed"] == index
        with factory() as db:
            correct = db.get(Activity, quiz["activity"]["id"]).private["correctChoiceId"]
        answer = client.post(path + "/answer", json={"operationId": f"baseline-{index}", "expectedLearnerVersion": quiz["version"], "choiceId": correct})
        assert answer.status_code == 202, answer.text
        assert work_once(factory, services)
        assessed = client.get(path).json()
        assert assessed["preAssessment"]["completed"] == index + 1
        response = client.post(path + "/start", json={"mode": "pre_assessment", "continuation": True, "stepId": assessed["stepId"]})
        assert assessed["evidenceStates"][quiz["activity"]["conceptId"]][quiz["activity"]["difficulty"]] == "demonstrated"
        if index < total - 1:
            assert response.status_code == 202, response.text
        else:
            assert response.status_code == 409
    assert all(item["preAssessment"] for item in assessed["history"])
    lesson = client.post(path + "/start", json={"mode": "lesson", "continuation": True, "stepId": assessed["stepId"]})
    assert lesson.status_code == 202, lesson.text
    assert lesson.json()["preAssessment"] is None
    assert all(item["preAssessment"] for item in lesson.json()["history"])
    assert lesson.json()["preAssessmentResume"] is True
    next_round = client.post(path + "/start", json={"mode": "pre_assessment", "continuation": True, "nextRound": True, "stepId": lesson.json()["stepId"]})
    assert next_round.status_code == 202, next_round.text
    assert next_round.json()["preAssessment"]["round"] == 2
    assert next_round.json()["preAssessment"]["completed"] == 0
    assert work_once(factory, services)
    review_question = client.get(path).json()["activity"]
    assert review_question and review_question["conceptId"] == quiz["activity"]["conceptId"]
    assert review_question["prompt"] != quiz["activity"]["prompt"]


def test_pre_assessment_covers_blocked_concepts(stack, monkeypatch):
    import copy
    from learnloop.agents.tutoring import agent as tutor_agent
    from learnloop.persistence.database import CourseRelease
    from learnloop.persistence.releases import fingerprint

    monkeypatch.setattr(tutor_agent, "select_question_format", lambda *args: "single_answer")
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    with factory.begin() as db:
        release = db.scalar(select(CourseRelease).where(CourseRelease.course_id == course_id))
        payload = copy.deepcopy(release.payload)
        original = payload["graph"]["concepts"][0]
        second = {**copy.deepcopy(original), "id": "second-concept", "title": "Second concept"}
        payload["graph"]["concepts"].append(second)
        payload["graph"]["prerequisites"].append({"prerequisite": original["id"], "dependent": second["id"]})
        for doc in payload["documents"]:
            resources = doc["graph"].get("resources", {})
            if original["id"] in resources:
                resources[second["id"]] = copy.deepcopy(resources[original["id"]])
        db.add(CourseRelease(course_id=course_id, version=release.version + 1, sha256=fingerprint(payload), payload=payload))
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Course baseline"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    response = client.post(path + "/start", json={"mode": "pre_assessment"})
    assert response.status_code == 202, response.text
    assert response.json()["preAssessment"]["total"] == 2
    assert work_once(factory, services)
    quiz = client.get(path).json()
    with factory() as db:
        correct = db.get(Activity, quiz["activity"]["id"]).private["correctChoiceId"]
    wrong = next(c["id"] for c in quiz["activity"]["choices"] if c["id"] != correct)
    assert client.post(path + "/answer", json={"operationId": "baseline-wrong", "expectedLearnerVersion": quiz["version"], "choiceId": wrong}).status_code == 202
    assert work_once(factory, services)
    assessed = client.get(path).json()
    assert assessed["evidenceStates"][original["id"]][quiz["activity"]["difficulty"]] != "demonstrated"
    next_response = client.post(path + "/start", json={"mode": "pre_assessment", "continuation": True, "stepId": assessed["stepId"]})
    assert next_response.status_code == 202, next_response.text
    assert work_once(factory, services)
    second_quiz = client.get(path).json()
    assert second_quiz["activity"]["conceptId"] == "second-concept", second_quiz


def test_pre_assessment_round_sizes_and_coverage():
    plan = [str(i) for i in range(32)]
    first = workbench_tutor.pre_assessment_round(plan, [], 1)
    assert first == plan[:15]
    second = workbench_tutor.pre_assessment_round(plan, first, 2)
    assert len(second) == 15
    assert second[:12] == plan[15:27]
    assert len(set(second) & set(first)) == 3
    third = workbench_tutor.pre_assessment_round(plan, first + second, 3)
    assert set(plan[27:]) <= set(third)
    assert len(third) <= 15
    review = workbench_tutor.pre_assessment_round(plan, plan, 4)
    assert len(review) == 15 and len(set(review)) == 15


def test_pre_assessment_not_sure_preserves_evidence_and_advances(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    memory_id = client.post(f"/api/workbench/courses/{course_id}/memories", json={"name": "Not sure"}).json()["id"]
    path = f"/api/workbench/memories/{memory_id}"
    assert client.post(path + "/start", json={"mode": "pre_assessment"}).status_code == 202
    assert work_once(factory, services)
    quiz = client.get(path).json()
    body = {"activityId": quiz["activity"]["id"], "operationId": "not-sure-1", "expectedLearnerVersion": quiz["version"]}
    response = client.post(path + "/not-sure", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assessment"]["notSure"] and result["assessment"]["uncertain"]
    assert result["evidence"] == quiz["evidence"]
    assert result["version"] == quiz["version"] + 1
    assert result["preAssessment"]["completed"] == 1
    assert result["history"][0]["assessment"]["notSure"]
    assert client.post(path + "/not-sure", json=body).status_code == 200
    assert client.get(path).json()["version"] == result["version"]
    assert client.post(path + "/answer", json={"operationId": "late-answer", "expectedLearnerVersion": result["version"], "choiceId": "a"}).status_code == 409
    assert client.post(path + "/start", json={"mode": "pre_assessment", "continuation": True, "nextRound": True, "stepId": result["stepId"]}).status_code == 202
