from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from learnloop.core.schemas import Assessment, Misconception, PlanChoice
from learnloop.persistence.database import Activity, PlanRevision, ResponseDetail, Submission
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare


def start(stack, course_id):
    client, factory, services, _ = stack
    version = client.get(f"/api/courses/{course_id}/learner-state").json()["version"]
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": version}
    ).json()
    assert work_once(factory, services)
    return client.get(f"/api/sessions/{session['id']}").json()


def submit(stack, session, choice="a", reasoning=None):
    client, factory, services, _ = stack
    version = client.get(f"/api/courses/{session['courseId']}/learner-state").json()["version"]
    body = {
        "operationId": f"answer-{session['activity']['id']}",
        "expectedLearnerVersion": version,
        "choiceId": choice,
        "reasoning": reasoning,
    }
    response = client.post(f"/api/activities/{session['activity']['id']}/responses", json=body)
    response.raise_for_status()
    assert work_once(factory, services)
    return response.json(), body


def test_goal_revision_is_owned_versioned_idempotent_and_used_by_tutor(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    concept = client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"][0]
    url = f"/api/courses/{course_id}/plan"
    assert client.get(url).json()["version"] == 0
    body = {
        "operationId": "goal-1",
        "expectedPlanVersion": 0,
        "expectedLearnerVersion": 0,
        "goal": {
            "description": "Understand gradient descent independently",
            "conceptIds": [concept["id"]],
        },
    }
    revision = client.post(url + "/revise", json=body)
    revision.raise_for_status()
    assert revision.json()["version"] == 1
    assert client.post(url + "/revise", json=body).json() == revision.json()
    assert client.post(url + "/revise", json={**body, "operationId": "stale"}).status_code == 409
    assert (
        client.post(
            url + "/revise", json={**body, "goal": {"description": "A different request"}}
        ).status_code
        == 409
    )
    assert client.get("/api/courses/missing/plan").status_code == 404
    session = start(stack, course_id)
    assert session["activity"]["action"] == "introduce"
    assert session["plan"]["version"] == 2 and session["plan"]["goal"] == body["goal"]
    with factory() as db:
        rows = list(db.scalars(select(PlanRevision).order_by(PlanRevision.version)))
        assert len(rows) == 2 and rows[0].snapshot == revision.json()
        assert rows[1].snapshot["candidates"][0]["factors"]["goalMatch"] == 1
    bad = {
        **body,
        "operationId": "foreign",
        "expectedPlanVersion": 2,
        "goal": {"description": "Foreign concept", "conceptIds": ["missing"]},
    }
    assert client.post(url + "/revise", json=bad).status_code == 422
    bad.update(goal=body["goal"], activityIds=["missing"])
    assert client.post(url + "/revise", json=bad).status_code == 404
    bad.update(activityIds=[], reviewDates=[{"conceptId": concept["id"], "reviewAt": "2026-10-25"}])
    assert client.post(url + "/revise", json=bad).status_code == 422


def test_model_cannot_invent_action_or_commit_a_stale_plan(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    original = services.generate

    def generate(role, instruction, context, output):
        if output is PlanChoice:
            return PlanChoice(
                candidateId="unpublished|introduce|advanced",
                rationale="Invalid proposal from a controlled model.",
            )
        return original(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", generate)
    session = start(stack, course_id)
    assert session["activity"] is None
    assert client.get(f"/api/courses/{course_id}/plan").json()["version"] == 0
    assert (
        client.get(f"/api/agent-activity/runs/{session['runIds'][-1]}").json()["error"]["code"]
        == "invalid_plan"
    )


def test_response_timing_rubric_and_prior_evidence_are_recorded_without_leaking_keys(
    stack, monkeypatch
):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = start(stack, course_id)
    activity = session["activity"]
    assert not any(
        k in str(activity) for k in ("correctChoiceId", "choiceScores", "referenceAnswer")
    )
    endpoint = f"/api/activities/{activity['id']}"
    first = client.post(endpoint + "/present").json()
    assert first == client.post(endpoint + "/present").json()
    with factory.begin() as db:
        saved = db.get(Activity, activity["id"])
        saved.private = {
            **saved.private,
            "presentedAt": (datetime.now(UTC) - timedelta(seconds=3)).isoformat(),
        }
    receipt, body = submit(stack, session, reasoning="Subtract the gradient to reduce loss.")
    assert client.post(endpoint + "/responses", json=body).json() == receipt
    assert (
        client.post(
            endpoint + "/responses", json={**body, "reasoning": "Changed reasoning"}
        ).status_code
        == 409
    )
    assessed = client.get(f"/api/sessions/{session['id']}").json()["assessment"]
    assert assessed["rubricScore"] == 1 and assessed["rubricCoverage"]
    assert (
        assessed["timing"]["responseTimeMs"] >= 3000
        and assessed["timing"]["basis"] == "presentation"
    )
    assert client.post(endpoint + "/present").status_code == 409
    with factory() as db:
        assert db.get(ResponseDetail, receipt["submissionId"]).reasoning == body["reasoning"]
    original = services.generate

    def observe(role, instruction, context, output):
        if output is Assessment:
            assert context["priorEvidence"]["assessmentIds"] == [receipt["submissionId"]]
            assert context["previousAssessments"][0]["assessmentId"] == receipt["submissionId"]
            assert (
                context["difficulty"] == "basic"
                and context["passages"]
                and context["rubric"]
            )
        return original(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", observe)
    client.post(
        f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": 1}
    ).raise_for_status()
    assert work_once(factory, services)
    session = client.get(f"/api/sessions/{session['id']}").json()
    assert session["activity"]["action"] == "practice"
    submit(stack, session)
    state = client.get(f"/api/courses/{course_id}/learner-state").json()
    assert state["overallStates"][activity["conceptId"]] == "demonstrated"


def test_choice_only_assessment_does_not_require_written_response_quotes(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = start(stack, course_id)
    original = services.generate

    def quoted_option(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Assessment:
            result.coverage[0].responseQuote = "Option A (no written explanation supplied)"
            result.misconceptions = [
                Misconception(
                    criterionId=result.coverage[0].criterionId,
                    responseQuote="Text the learner never wrote",
                    description="Unsupported misconception",
                )
            ]
        return result

    monkeypatch.setattr(services, "generate", quoted_option)
    submit(stack, session)
    assessed = client.get(f"/api/sessions/{session['id']}").json()["assessment"]
    assert assessed["correct"] and assessed["rubricScore"] == 1
    assert assessed["rubricCoverage"][0]["responseQuote"] == ""
    assert assessed["misconceptions"] == []
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1


def test_partial_reasoning_never_grants_demonstration_and_false_quotes_stop_commit(
    stack, monkeypatch
):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = start(stack, course_id)
    original = services.generate

    def partial(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Assessment:
            result.coverage[0].score = 0.5
        return result

    monkeypatch.setattr(services, "generate", partial)
    submit(stack, session, reasoning="Subtract the gradient.")
    assessed = client.get(f"/api/sessions/{session['id']}").json()["assessment"]
    assert assessed["correct"] and assessed["partial"] and assessed["rubricScore"] == 0.5
    state = client.get(f"/api/courses/{course_id}/learner-state").json()
    assert not state["concepts"][session["activity"]["conceptId"]]["basic"][
        "independentActivityIds"
    ]
    client.post(
        f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": 1}
    ).raise_for_status()
    assert work_once(factory, services)
    session = client.get(f"/api/sessions/{session['id']}").json()
    assert session["activity"]["difficulty"] == "basic"

    def false_quote(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Assessment:
            result.coverage[0].responseQuote = "Text the learner never wrote"
        return result

    monkeypatch.setattr(services, "generate", false_quote)
    receipt, _ = submit(stack, session, reasoning="My own answer")
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1
    assert (
        client.get(f"/api/agent-activity/runs/{receipt['runId']}").json()["error"]["code"]
        == "invalid_response_evidence"
    )


def test_missing_rubric_coverage_cannot_change_evidence(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = start(stack, course_id)
    original = services.generate

    def missing(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Assessment:
            result.coverage = []
        return result

    monkeypatch.setattr(services, "generate", missing)
    receipt, _ = submit(stack, session)
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0
    with factory() as db:
        assert not db.get(Submission, receipt["submissionId"]).assessment


def test_plan_change_during_model_call_prevents_assignment(stack, monkeypatch):
    client, _, services, _ = stack
    course_id, _ = prepare(stack)
    original = services.generate

    def change_plan(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is PlanChoice:
            response = client.post(
                f"/api/courses/{course_id}/plan/revise",
                json={
                    "operationId": "concurrent-revision",
                    "expectedPlanVersion": 0,
                    "expectedLearnerVersion": 0,
                    "goal": {"description": "A revised learning goal"},
                },
            )
            response.raise_for_status()
        return result

    monkeypatch.setattr(services, "generate", change_plan)
    session = start(stack, course_id)
    assert session["activity"] is None
    assert (
        client.get(f"/api/agent-activity/runs/{session['runIds'][-1]}").json()["error"]["code"]
        == "learner_changed"
    )
    assert client.get(f"/api/courses/{course_id}/plan").json()["version"] == 1


def test_misconception_and_contradiction_keep_assessment_history(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = start(stack, course_id)
    first, _ = submit(stack, session)
    client.post(
        f"/api/sessions/{session['id']}/next", json={"expectedLearnerVersion": 1}
    ).raise_for_status()
    assert work_once(factory, services)
    session = client.get(f"/api/sessions/{session['id']}").json()
    second, _ = submit(stack, session)
    original = services.generate

    def misconception(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is Assessment:
            result = Assessment.model_validate(
                {
                    **result.model_dump(),
                    "misconceptions": [
                        {
                            "criterionId": context["rubric"][0]["id"],
                            "description": "Adds the gradient instead of subtracting it.",
                            "responseQuote": "Add the gradient",
                        }
                    ],
                }
            )
        return result

    monkeypatch.setattr(services, "generate", misconception)
    session = client.post(
        f"/api/courses/{course_id}/sessions",
        json={"expectedLearnerVersion": 2, "conceptId": session["activity"]["conceptId"]},
    ).json()
    assert work_once(factory, services)
    session = client.get(f"/api/sessions/{session['id']}").json()
    third, _ = submit(stack, session, choice="b")
    assessed = client.get(f"/api/sessions/{session['id']}").json()["assessment"]
    assert assessed["contradiction"] and assessed["misconceptions"] and not assessed["partial"]
    evidence = client.get(f"/api/courses/{course_id}/learner-state").json()["concepts"][
        session["activity"]["conceptId"]
    ]["basic"]
    assert evidence["state"] == "review_due"
    assert evidence["assessmentIds"] == [
        first["submissionId"],
        second["submissionId"],
        third["submissionId"],
    ]
    assert evidence["contradictions"][0]["priorAssessmentIds"] == [
        first["submissionId"],
        second["submissionId"],
    ]


def test_legacy_question_receives_reviewed_rubric_without_rewriting_course_pack(stack):
    from learnloop.persistence.database import Document

    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = dict(doc.graph)
        import copy

        graph = copy.deepcopy(graph)
        for pack in graph["resources"].values():
            for question in pack["tests"]:
                question.pop("rubric", None)
                question.pop("referenceAnswer", None)
        doc.graph = graph
    session = start(stack, course_id)
    assert session["activity"]
    with factory() as db:
        question = db.get(Activity, session["activity"]["id"]).private["question"]
        assert question["rubric"] and question["referenceAnswer"]
        assert db.get(Document, upload["documentId"]).graph == graph
    submit(stack, session)
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1
