from learnloop.agents.expert.analysis import _merge_section, section_passages
from learnloop.core.domain import validate_graph
from learnloop.core.schemas import ConceptMatches, Graph


def concept(id, title):
    return {
        "id": id,
        "title": title,
        "summary": "A distinct learning goal with supporting source material.",
        "sources": [{"chunkId": id, "quote": "A supporting passage for this learning goal."}],
    }


def test_sections_include_every_passage_once_in_order_and_handle_dense_pages():
    chunks = [
        {"id": str(i), "page": i // 5 + 1, "text": "x" * (1400 if i != 20 else 12000)}
        for i in range(83)
    ]
    sections = section_passages(chunks)
    assert [c["id"] for section in sections for c in section] == [c["id"] for c in chunks]
    assert all(len(section) <= 8 for section in sections)
    assert all(
        sum(len(c["text"]) for c in section) <= 10000 or len(section) == 1 for section in sections
    )
    assert section_passages([]) == []


def test_semantic_merges_preserve_existing_ids_and_keep_distinct_new_goals():
    class Services:
        def generate(self, role, instruction, context, output):
            return ConceptMatches(matches=[{"candidateId": "alias", "existingId": "document:old"}])

    catalog = [concept("document:old", "Existing goal")]
    mapping = _merge_section(
        Services(),
        {
            "concepts": [
                concept("alias", "Synonym for existing goal"),
                concept("new", "A new mechanism"),
            ],
            "prerequisites": [],
        },
        catalog,
        "document",
    )
    assert mapping["alias"] == "document:old"
    assert len(catalog) == 2 and catalog[0]["id"] == "document:old"
    assert "alias" in catalog[0]["sourceChunkIds"]


def test_concept_count_can_exceed_previous_global_cap_and_deep_graph_is_iterative():
    graph = Graph.model_validate(
        {"concepts": [concept(f"goal-{i}", f"Goal {i}") for i in range(45)]}
    )
    validate_graph(graph)
    # Large prerequisite chains must not hit Python's recursion limit.
    validate_graph(
        {
            "concepts": [concept(str(i), str(i)) for i in range(1500)],
            "prerequisites": [
                {"prerequisite": str(i), "dependent": str(i + 1)} for i in range(1499)
            ],
        }
    )
