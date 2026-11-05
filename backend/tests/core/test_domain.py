from datetime import UTC, datetime, timedelta

import pytest

from learnloop.core.domain import (
    assess_evidence,
    effective_state,
    extract,
    select_concept,
    validate_graph,
)
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import Graph, Question


def test_hint_and_repeated_activity_do_not_inflate_mastery():
    at = datetime.now(UTC)
    _, assisted = assess_evidence(None, "q0", True, True, False, at)
    assert assisted["state"] == "developing" and assisted["independentActivityIds"] == []
    _, one = assess_evidence(assisted, "q1", True, False, False, at)
    _, repeated = assess_evidence(one, "q1", True, False, False, at)
    assert repeated["state"] == "developing"
    _, two = assess_evidence(repeated, "q2", True, False, False, at)
    assert two["state"] == "demonstrated"
    assert effective_state(two, at + timedelta(days=8)) == "review_due"


def test_contradictions_uncertainty_and_due_review_need_new_evidence():
    at = datetime.now(UTC)
    _, one = assess_evidence(None, "q1", True, False, False, at)
    _, two = assess_evidence(one, "q2", True, False, False, at)
    before, failed = assess_evidence(two, "q3", False, False, False, at)
    assert before == "demonstrated" and failed["state"] == "review_due"
    assert failed["independentActivityIds"] == [] and two["independentActivityIds"] == [
        "q1",
        "q2",
    ]
    _, uncertain = assess_evidence(one, "q3", True, False, True, at)
    assert uncertain["state"] == "developing" and not uncertain["independentActivityIds"]
    _, review = assess_evidence(two, "q4", True, False, False, at + timedelta(days=8))
    assert review["state"] == "developing" and review["independentActivityIds"] == ["q4"]


def test_graph_allows_unverified_citations_but_rejects_cycles_and_duplicates():
    source = {"chunkId": "c1", "quote": "A derivative describes change."}
    concept = {
        "id": "derivative",
        "title": "Derivative",
        "summary": "A derivative describes change.",
        "sources": [source],
    }
    graph = Graph.model_validate(
        {"concepts": [concept, {**concept, "id": "gradient"}], "prerequisites": []}
    )
    validate_graph(graph)
    bad = graph.model_copy(deep=True)
    bad.concepts[0].sources[0].quote = "This quote was invented."
    validate_graph(bad)
    bad.concepts[0].sources[0].chunkId = "outside-this-document"
    validate_graph(bad)
    cyclic = Graph.model_validate(
        {
            "concepts": [concept, {**concept, "id": "gradient"}],
            "prerequisites": [
                {
                    "prerequisite": "derivative",
                    "dependent": "gradient",
                    "source": source,
                },
                {
                    "prerequisite": "gradient",
                    "dependent": "derivative",
                    "source": source,
                },
            ],
        }
    )
    with pytest.raises(ServiceError, match="cycle"):
        validate_graph(cyclic)
    duplicate = Graph.model_validate({"concepts": [concept, concept]})
    with pytest.raises(ServiceError, match="unique"):
        validate_graph(duplicate)


def test_prerequisites_block_and_review_has_priority():
    graph = {
        "concepts": [{"id": "a"}, {"id": "b"}],
        "prerequisites": [{"prerequisite": "a", "dependent": "b"}],
    }
    assert select_concept(graph, {})["id"] == "a"
    assert select_concept(graph, {"a": {"intermediate": {"state": "demonstrated"}}})["id"] == "b"
    assert select_concept(graph, {"a": {"intermediate": {"state": "review_due"}}})["id"] == "a"


def test_extraction_preserves_pages_and_rejects_invalid_inputs():
    content = ("Gradient descent subtracts the gradient to reduce the loss. " * 70).encode()
    pages, chunks = extract(content, "notes.txt", 200, 1000)
    assert pages == 1 and len(chunks) > 1 and all(c["page"] == 1 for c in chunks)
    for content, filename in [
        (b"not pdf", "notes.pdf"),
        (b"\xff", "notes.txt"),
        (b"", "notes.txt"),
    ]:
        with pytest.raises(ServiceError):
            extract(content, filename, 200, 1000)
    with pytest.raises(ServiceError):
        extract(b"A" * 5000, "notes.txt", 200, 1)


def test_question_requires_distinct_choices():
    data = {
        "prompt": "Which direction reduces the loss?",
        "explanation": "Move opposite to the gradient.",
        "hint": "Think about the direction of increase.",
        "correctChoiceId": "a",
        "sources": [{"chunkId": "c1", "quote": "The gradient points uphill."}],
        "choices": [{"id": key, "text": "Same option"} for key in "abcd"],
    }
    with pytest.raises(ValueError):
        Question.model_validate(data)
