import pytest

from learnloop.agents.expert.candidate_index import ConceptCandidateIndex


def test_candidate_index_ranks_relevant_concepts_and_limits_results():
    concepts = [
        {"id": "b", "title": "Online softmax", "summary": "Combine attention blocks"},
        {"id": "a", "title": "Attention memory", "summary": "Score matrix"},
        {"id": "c", "title": "Gradient descent", "summary": "Model training"},
    ]
    index = ConceptCandidateIndex(concepts)
    assert [c["id"] for c in index.search({"title": "Online softmax attention"}, 1)] == ["b"]
    assert index.search({"title": "unrelated vocabulary"}) == []
    assert index.search({"id": "b", "title": "online softmax"}) == []
    assert index.search({"title": "attention"}, 0) == []


def test_candidate_index_rejects_duplicate_ids_and_breaks_ties_stably():
    concepts = [{"id": "b", "title": "attention"}, {"id": "a", "title": "attention"}]
    assert [c["id"] for c in ConceptCandidateIndex(concepts).search({"title": "attention"})] == ["a", "b"]
    with pytest.raises(ValueError):
        ConceptCandidateIndex(concepts + [concepts[0]])


def test_duplicate_review_resumes_completed_candidates(stack, monkeypatch):
    import copy

    from learnloop.agents.expert.deduplication import deduplicate_course
    from learnloop.core.errors import ServiceError
    from learnloop.core.schemas import ConceptMatches
    from learnloop.persistence.database import Course, Document
    from learnloop.runtime.events import new_run
    from tests.api.test_integration import prepare

    _client, factory, services, _settings = stack
    course_id, first = prepare(stack)
    with factory.begin() as db:
        existing = db.get(Document, first["documentId"])
        concept = existing.graph["concepts"][0]
        draft = Document(
            id="new-document", course_id=course_id, filename="new.txt",
            sha256="f" * 64, content_type="text/plain", content=b"new", status="prepared",
            graph={"concepts": [
                {**copy.deepcopy(concept), "id": "new:a"},
                {**copy.deepcopy(concept), "id": "new:b"},
            ], "prerequisites": []},
        )
        db.add(draft)
        run = new_run(db, db.get(Course, course_id), "course_preparation", {"document_id": draft.id})
        run_id = run.id
    calls = []

    def generate(_role, _instruction, context, output):
        assert output is ConceptMatches
        candidate = context["candidates"][0]["id"]
        calls.append(candidate)
        if candidate == "new:b" and calls.count(candidate) == 1:
            raise ServiceError("temporary", "Interrupted", True)
        return ConceptMatches(matches=[])

    monkeypatch.setattr(services, "generate", generate)
    with pytest.raises(ServiceError):
        deduplicate_course(factory, services, run_id, "new-document")
    deduplicate_course(factory, services, run_id, "new-document")
    assert calls == ["new:a", "new:b", "new:b"]
