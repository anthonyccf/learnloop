import pytest

from learnloop.core.schemas import (
    Assessment,
    ExpertSolution,
    FillInQuestion,
    MultipleAnswerQuestion,
    OpenQuestion,
)
from learnloop.persistence.database import Activity
from learnloop.runtime.worker import work_once
from tests.api.test_difficulty import prepare


@pytest.mark.parametrize(
    "target,formats,selection,expected_score",
    [
        ("basic", ["single_answer", "fill_in"], None, 1),
        ("intermediate", ["multiple_answer", "fill_in"], None, 1),
        ("advanced", ["open"], None, 1),
        ("intermediate", ["multiple_answer"], ["a", "c"], 0.5),
        ("intermediate", ["multiple_answer"], ["a", "b", "c"], 1),
    ],
)
def test_expert_generates_verifies_and_assigns_mixed_questions(stack, monkeypatch, target, formats, selection, expected_score):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    concept = client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"][0]
    target_update = client.post(
        f"/api/courses/{course_id}/concepts/{concept['id']}/target",
        json={
            "targetDifficulty": target,
            "expectedLearnerVersion": 0,
        },
    )
    target_update.raise_for_status()
    initial_version = target_update.json()["learnerVersion"]
    generate = services.generate
    verified_formats = []

    def provider(role, instruction, context, output):
        if output in (MultipleAnswerQuestion, FillInQuestion, OpenQuestion):
            assert role == "Expert"
            passage = context["passages"][0]
            citation = {"chunkId": passage["chunkId"], "quote": passage["text"][:60]}
            common = {
                "difficulty": context["difficulty"],
                "explanation": "A gradient step moves toward a smaller loss.",
                "hint": "Consider which direction reduces the loss.",
                "sources": [citation],
                "referenceAnswer": "Subtract the gradient to move toward lower loss.",
                "rubric": [
                    {
                        "id": "direction",
                        "description": "Identifies the update direction.",
                        "weight": 1,
                        "sources": [citation],
                    }
                ],
            }
            if output is MultipleAnswerQuestion:
                common["rubric"][0]["choiceIds"] = ["a", "b"]
                return output(
                    **common,
                    prompt="Which two statements describe gradient descent?",
                    choices=[
                        {"id": key, "text": text}
                        for key, text in zip(
                            "abcd",
                            [
                                "Subtract the gradient",
                                "Scale the step by the learning rate",
                                "Add the gradient",
                                "Always double the weights",
                            ],
                        )
                    ],
                    correctChoiceIds=["a", "b"],
                )
            if output is FillInQuestion:
                return output(
                    **common,
                    prompt="To reduce the loss, [[direction]] from the weights.",
                    blanks=[
                        {"id": "direction", "acceptedAnswers": ["subtract the gradient"]},
                    ],
                )
            return output(**common, prompt="Explain why the gradient update can reduce the loss.")
        if output is ExpertSolution:
            assert not (
                {"referenceAnswer", "rubric", "correctChoiceIds", "blanks"} & context.keys()
            )
            question_format = context["format"]
            verified_formats.append(question_format)
            return ExpertSolution(
                uncertain=False,
                **{
                    "multiple_answer": {"choiceIds": ["b", "a"]},
                    "fill_in": {"blanks": [{"id": "direction", "text": "Subtract the gradient"}]},
                    "open": {
                        "answerText": "The gradient points toward increasing loss, so subtract it."
                    },
                }[question_format],
            )
        if output is Assessment and "answerText" in context:
            return Assessment(
                feedback="You identified the descent direction.",
                uncertain=False,
                coverage=[
                    {
                        "criterionId": "direction",
                        "score": 1,
                        "reason": "Correct descent direction.",
                        "responseQuote": "Subtract the gradient",
                    }
                ],
            )
        return generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", provider)
    launch = client.post(
        f"/api/courses/{course_id}/sessions",
        json={
            "expectedLearnerVersion": initial_version,
            "mixedQuestionFormats": True,
        },
    )
    launch.raise_for_status()
    session_url = f"/api/sessions/{launch.json()['id']}"
    for index, expected in enumerate(formats):
        version = initial_version + index
        assert work_once(factory, services)
        item = client.get(session_url).json()["activity"]
        assert item.get("format", "single_answer") == expected and item["difficulty"] == target
        assert not (
            {"referenceAnswer", "rubric", "correctChoiceIds", "acceptedAnswers"} & item.keys()
        )
        path = f"/api/activities/{item['id']}/responses"
        operation = {"operationId": f"mixed-{version}", "expectedLearnerVersion": version}
        if expected != "single_answer":
            assert client.post(path, json={**operation, "choiceId": "a"}).status_code == 422
        with factory() as db:
            correct_choice = db.get(Activity, item["id"]).private.get("correctChoiceId")
        answer = {
            "single_answer": {"choiceId": correct_choice},
            "multiple_answer": {"choiceIds": selection or ["b", "a"]},
            "fill_in": {"blanks": [{"id": "direction", "text": "SUBTRACT  THE gradient"}]},
            "open": {"answerText": "Subtract the gradient to move toward lower loss."},
        }[expected]
        receipt = client.post(path, json={**operation, **answer})
        receipt.raise_for_status()
        assert client.post(path, json={**operation, **answer}).json() == receipt.json()
        assert work_once(factory, services)
        assessed = client.get(session_url).json()
        assessment = assessed["assessment"]
        assert assessment["rubricScore"] == expected_score
        assert assessment["correct"] is (selection is None)
        if selection is not None:
            assert assessment["partial"] and "Incorrectly selected" in assessment["feedback"]
        if expected != "single_answer":
            assert assessed["answer"] and assessed["selectedChoiceId"] is None
        if index + 1 < len(formats):
            client.post(
                f"{session_url}/next", json={"expectedLearnerVersion": version + 1}
            ).raise_for_status()
    assert verified_formats == [fmt for fmt in formats if fmt != "single_answer"]
