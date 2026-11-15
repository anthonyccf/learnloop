import pytest
from pydantic import ValidationError

from learnloop.agents.assessing.mixed_answers import assess_mixed
from learnloop.core.schemas import MultipleAnswerQuestion


def question():
    source = {"chunkId": "chunk-1", "quote": "A source passage supporting this question."}
    return MultipleAnswerQuestion(
        difficulty="intermediate", prompt="Which statements are correct?",
        explanation="The first two statements are supported.", hint="Consider each statement.",
        sources=[source], referenceAnswer="The first two statements are correct.",
        choices=[{"id": x, "text": "Statement " + x} for x in "abcd"],
        correctChoiceIds=["a", "b"],
        rubric=[{"id": x, "description": "Identifies statement " + x,
                 "weight": 1, "sources": [source], "choiceIds": [x]} for x in "ab"],
    )


@pytest.mark.parametrize("selected,expected", [
    (["a", "b"], 1), (["a"], 0.5), (["a", "c"], 0.5),
    (["a", "b", "c"], 1), (["a", "b", "c", "d"], 1),
])
def test_partial_score_and_distractors(selected, expected):
    _, coverage, score = assess_mixed(None, question(), {}, {"choiceIds": selected})
    assert score == expected
    assert len(coverage) == 2


def test_invalid_mapping_rejected_and_legacy_exact_only():
    data = question().model_dump()
    data["rubric"][0]["choiceIds"] = ["c"]
    with pytest.raises(ValidationError):
        MultipleAnswerQuestion.model_validate(data)
    for item in data["rubric"]:
        item["choiceIds"] = []
    _, _, score = assess_mixed(None, MultipleAnswerQuestion.model_validate(data), {}, {"choiceIds": ["a"]})
    assert score == 0
