from types import SimpleNamespace

import pytest

from learnloop.agents.question_review import question_review_valid, review_question
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import grounding_valid
from learnloop.core.schemas import ExtendedTopicReview, GroundingReview

ITEM = {"prompt": "Related quiz", "sources": [{"chunkId": "one", "quote": "Alignment"}]}
CHUNKS = {"one": {"text": "Alignment"}}
CONCEPT = {"title": "Section alignment"}


@pytest.mark.parametrize("status", ["unsupported", "uncertain"])
def test_expert_can_approve_extension_and_receipt_survives_assessment(status):
    calls = []

    def generate(role, prompt, context, output):
        calls.append(role)
        if output is GroundingReview:
            return GroundingReview(status=status, summary="The lecture omits this detail.")
        assert output is ExtendedTopicReview and role == "Expert"
        assert context["concept"] == CONCEPT
        return ExtendedTopicReview(
            approved=True, reason="Memory alignment builds on the lecture's section layout topic."
        )

    services = SimpleNamespace(generate=generate)
    receipt = review_question(services, "Tutoring", ITEM, CHUNKS, concept=CONCEPT)
    assert receipt["status"] == "extended"
    assert question_review_valid(ITEM, CHUNKS, receipt)
    assert not grounding_valid(ITEM, CHUNKS, receipt)
    assert review_question(services, "Assessing", ITEM, CHUNKS, receipt) == receipt
    assert calls == ["Tutoring", "Expert"]
    assert not question_review_valid({**ITEM, "prompt": "Changed question"}, CHUNKS, receipt)
    assert not question_review_valid(ITEM, {"one": {"text": "Changed lecture"}}, receipt)
    assert not question_review_valid(ITEM, CHUNKS, {**receipt, "reviewedBy": "Tutoring"})


def test_incorrect_or_unapproved_extension_still_blocks():
    def generate(role, prompt, context, output):
        if output is GroundingReview:
            return GroundingReview(status="unsupported", summary="Incorrect or unsupported answer.")
        return ExtendedTopicReview(
            approved=False, reason="The proposed question is not factually correct."
        )

    with pytest.raises(ServiceError, match="Course evidence"):
        review_question(
            SimpleNamespace(generate=generate), "Tutoring", ITEM, CHUNKS, concept=CONCEPT
        )


def test_invalid_citations_never_become_extensions():
    def generate(*args):
        pytest.fail("Foreign citations must fail without model review")

    with pytest.raises(ServiceError):
        review_question(SimpleNamespace(generate=generate), "Tutoring", ITEM, {}, concept=CONCEPT)
