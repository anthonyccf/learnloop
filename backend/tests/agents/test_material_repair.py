import copy

import pytest

from learnloop.agents.expert.repair import repair_citations, repair_context
from learnloop.core.schemas import PyramidMaterials, GroundingReview
from learnloop.persistence.database import Document
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare


def test_citation_lookup_requires_unique_quote_and_nearby_id():
    quote = "A learning rate determines the step size."
    draft = {"sources": [{"chunkId": "source-01", "quote": quote}]}
    fixed, changes = repair_citations(draft, {"source-02": {"text": quote}})
    assert fixed["sources"][0]["chunkId"] == "source-02"
    assert changes and draft["sources"][0]["chunkId"] == "source-01"
    for chunks in [
        {"source-02": {"text": "An unrelated passage with different evidence."}},
        {"source-02": {"text": quote}, "source-03": {"text": quote}},
        {"external-reference": {"text": quote}},
    ]:
        assert repair_citations(draft, chunks) == (draft, [])


def test_repair_retrieves_more_document_passages():
    chunks = [{"id": str(i), "ordinal": i, "text": "Other content"} for i in range(20)]
    chunks[19]["text"] = "HTTP adapter request response parameters"
    result = repair_context(
        {"title": "HTTP adapter", "summary": "Requests"},
        chunks,
        chunks[:6],
        {"lesson": {}},
        {"review": {"summary": "Find HTTP request response evidence"}},
        1,
    )
    assert len(result) == 12 and result[:6] == chunks[:6]
    assert chunks[19] in result


@pytest.mark.parametrize("failure", ["typo", "unsupported", "unrepairable"])
def test_existing_failed_pack_is_repaired_or_remains_withheld(stack, monkeypatch, failure):
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        cid = graph["concepts"][0]["id"]
        pack = graph["resources"][cid]
        original_tests = copy.deepcopy(pack["tests"])
        # A verified sibling must remain byte-for-byte unchanged during repair.
        sibling = copy.deepcopy(graph["concepts"][0])
        sibling["id"] = cid + "-retained"
        sibling["title"] = "A retained distinct foundation"
        graph["concepts"].append(sibling)
        graph["curriculum"]["objectives"][sibling["id"]] = {
            "conceptId": sibling["id"],
            "layer": "basic",
            "teaches": sibling["title"] + ": " + sibling["summary"],
            "assumes": [],
            "adds": "Understand this source-supported foundation.",
        }
        graph["resources"][sibling["id"]] = copy.deepcopy(pack)
        from learnloop.persistence.releases import scope_fingerprint

        graph["resources"][sibling["id"]]["scopeFingerprint"] = scope_fingerprint(
            pack["lesson"], graph["curriculum"]["objectives"][sibling["id"]]
        )
        retained = copy.deepcopy(graph["resources"][sibling["id"]])
        pack.pop("grounding")
        if failure == "typo":
            source = pack["tests"][0]["sources"][0]
            source["chunkId"] = ("0" if source["chunkId"][0] != "0" else "1") + source["chunkId"][
                1:
            ]
        else:
            pack["tests"][0]["explanation"] = "UNSUPPORTED CLAIM"
        doc.graph = graph
    before = client.get(f"/api/courses/{course_id}/learner-state").json()
    generate = services.generate
    repairs, reviews = [], []

    def tracked(role, instruction, context, output):
        if output is PyramidMaterials:
            repairs.append(context)
            if len(repairs) == 1:
                assert context["rejectedDraft"]["tests"][0]["explanation"] == "UNSUPPORTED CLAIM"
            assert context["sourceReviewFeedback"]
        result = generate(role, instruction, context, output)
        if output is GroundingReview and "lesson" in context["item"]:
            reviews.append(context)
            if failure == "unrepairable" or "UNSUPPORTED CLAIM" in str(context["item"]):
                result.status = "unsupported"
                result.summary = "The test explanation contains an unsupported claim."
        return result

    monkeypatch.setattr(services, "generate", tracked)
    receipt = client.post(f"/api/documents/{upload['documentId']}/materials").json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{receipt['runId']}").json()
    with factory() as db:
        updated = db.get(Document, upload["documentId"]).graph["resources"]
        assert updated[sibling["id"]] == retained
        if failure == "unrepairable":
            assert run["status"] == "needs_review"
            assert "grounding" not in updated[cid]
            assert len(repairs) == 2 and len(reviews) == 3
        else:
            assert run["status"] == "completed"
            assert updated[cid]["grounding"]["status"] == "supported"
            if failure == "typo":
                assert updated[cid]["tests"] == original_tests and not repairs
            else:
                assert "UNSUPPORTED CLAIM" not in str(updated[cid])
                assert len(repairs) == 1
    assert (
        client.get(f"/api/courses/{course_id}/learner-state").json()["concepts"]
        == before["concepts"]
    )
