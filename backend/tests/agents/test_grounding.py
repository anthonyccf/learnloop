from types import SimpleNamespace

import pytest

from learnloop.agents.grounding import generate_grounded, review_grounding
from learnloop.agents.references import refs
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import grounding_valid, validate_sources
from learnloop.core.schemas import GroundingReview, SectionGraph, Source

PASSAGES = {"chunk": {"text": "Subtract the gradient to reduce loss."}}
ITEM = {
    "summary": "Move opposite to the gradient.",
    "sources": [{"chunkId": "chunk", "quote": "The update moves downhill."}],
}


@pytest.mark.parametrize("sources", [[], [{"chunkId": "foreign", "quote": "Unsupported citation"}]])
def test_citation_validation_rejects_empty_or_unknown_sources_without_model_call(sources):
    def generate(*args):
        pytest.fail("Invalid IDs must fail before calling the model")

    with pytest.raises(ServiceError):
        review_grounding(
            SimpleNamespace(generate=generate), "Expert", {"sources": sources}, PASSAGES
        )


@pytest.mark.parametrize("status", ["unsupported", "uncertain"])
def test_known_passage_does_not_bypass_negative_or_uncertain_semantic_review(status):
    def generate(role, instruction, context, output):
        assert context["passages"][0]["text"] == PASSAGES["chunk"]["text"]
        assert output is GroundingReview
        return GroundingReview(status=status, summary="Evidence is not sufficient.")

    with pytest.raises(ServiceError) as failure:
        review_grounding(SimpleNamespace(generate=generate), "Expert", ITEM, PASSAGES)
    assert not failure.value.retryable
    assert failure.value.code == (
        "unsupported_content" if status == "unsupported" else "insufficient_evidence"
    )


def test_review_receipt_is_bound_to_content_passages_and_supported_status():
    calls = []

    def generate(*args):
        calls.append(args)
        return GroundingReview(status="supported", summary="Faithful source paraphrase.")

    services = SimpleNamespace(generate=generate)
    receipt = review_grounding(services, "Expert", ITEM, PASSAGES)
    assert grounding_valid(ITEM, PASSAGES, receipt)
    assert review_grounding(services, "Expert", ITEM, PASSAGES, receipt) == receipt
    assert len(calls) == 1
    assert not grounding_valid({**ITEM, "summary": "Add the gradient."}, PASSAGES, receipt)
    assert not grounding_valid(ITEM, {"chunk": {"text": "A different passage."}}, receipt)
    assert not grounding_valid(ITEM, PASSAGES, {**receipt, "status": "uncertain"})


def test_nested_bad_test_citation_and_empty_reference_projection_cannot_pass():
    with pytest.raises(ServiceError):
        validate_sources(
            {"lesson": ITEM, "tests": [{"sources": [{"chunkId": "foreign"}]}]}, PASSAGES
        )
    with pytest.raises(ServiceError):
        refs([Source(chunkId="foreign", quote="A made up source quote.")], PASSAGES)
    with pytest.raises(ServiceError):
        refs([], PASSAGES)


def test_rejected_draft_receives_review_feedback_and_must_pass_a_fresh_review():
    reviews, revisions = [], []

    def generate(role, instruction, context, output):
        if output is GroundingReview:
            reviews.append(context)
            return GroundingReview(
                status="unsupported" if len(reviews) == 1 else "supported",
                summary="Remove the unsupported stack sizes.",
            )
        revisions.append(context)
        assert "unsupported stack sizes" in context["sourceReviewFeedback"]["review"]["summary"]
        assert context["rejectedDraft"] == ITEM
        return ITEM

    result, receipt = generate_grounded(
        SimpleNamespace(generate=generate),
        "Expert",
        "Grounded output",
        {},
        dict,
        PASSAGES,
        candidate=ITEM,
    )
    assert result == ITEM and grounding_valid(ITEM, PASSAGES, receipt)
    assert len(reviews) == 2 and len(revisions) == 1


def test_grounding_repairs_stop_after_three_rejections_and_keep_diagnostics():
    calls = []

    def generate(role, instruction, context, output):
        calls.append(output)
        return (
            GroundingReview(status="uncertain", summary="No adequate course support.")
            if output is GroundingReview
            else ITEM
        )

    with pytest.raises(ServiceError) as failure:
        generate_grounded(
            SimpleNamespace(generate=generate),
            "Expert",
            "Grounded output",
            {},
            dict,
            PASSAGES,
            candidate=ITEM,
        )
    assert calls.count(GroundingReview) == 3 and calls.count(dict) == 2
    assert failure.value.details["review"]["status"] == "uncertain"
    assert not failure.value.retryable


def test_repair_can_omit_unsupported_concepts_without_fabricating_section_content():
    def generate(role, instruction, context, output):
        if output is GroundingReview:
            return GroundingReview(
                status="unsupported", summary="The cited page contains only Q & A."
            )
        return SectionGraph(concepts=[], prerequisites=[])

    result, receipt = generate_grounded(
        SimpleNamespace(generate=generate),
        "Expert",
        "Read section",
        {},
        SectionGraph,
        PASSAGES,
        candidate={"concepts": [ITEM], "prerequisites": []},
    )
    assert result.concepts == [] and receipt is None
