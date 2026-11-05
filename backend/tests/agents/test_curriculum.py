import pytest
from learnloop.agents.expert.curriculum import validate_curriculum
from learnloop.core.errors import ServiceError
from learnloop.persistence.repository import curriculum_order


def fixture():
    concepts = [{"id": x} for x in "abcde"]
    edges = [{"prerequisite": p, "dependent": c} for p, c in [("a","d"),("b","d"),("d","e"),("c","e")]]
    plan = {"objectives": [{"conceptId": x, "layer": "basic" if x in "abc" else "intermediate" if x == "d" else "advanced", "teaches": f"Exclusive teaching scope for {x}", "adds": f"New capability for objective {x}", "assumes": [] if x in "abc" else ["a","b"] if x == "d" else ["d","c"]} for x in "abcde"]}
    return concepts, edges, plan


def test_connected_pyramid_and_separate_mastery_target():
    concepts, edges, plan = fixture()
    validate_curriculum(plan, concepts, edges)
    assignments = {i["conceptId"]: i for i in plan["objectives"]}
    enriched = [{**c, "targetDifficulty": "advanced", "curriculum": assignments[c["id"]]} for c in reversed(concepts)]
    ordered = curriculum_order(enriched, edges)
    assert [c["curriculum"]["layer"] for c in ordered] == ["basic"]*3 + ["intermediate", "advanced"]
    assert all(c["targetDifficulty"] == "advanced" for c in ordered)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unconnected", "reversed", "scope", "unknown"])
def test_rejects_broken_or_repeated_curriculum(fault):
    concepts, edges, plan = fixture()
    if fault == "missing": plan["objectives"].pop()
    if fault == "duplicate": plan["objectives"].append(plan["objectives"][0])
    if fault == "unconnected": plan["objectives"][0]["layer"] = "intermediate"
    if fault == "reversed": plan["objectives"][3]["layer"] = "advanced"
    if fault == "scope": plan["objectives"][1]["teaches"] = plan["objectives"][0]["teaches"]
    if fault == "unknown": plan["objectives"][4]["assumes"].append("unknown")
    with pytest.raises(ServiceError):
        validate_curriculum(plan, concepts, edges)


def test_transitively_reduced_application_chain_can_share_a_layer():
    concepts = [{"id": x} for x in "abcdefgh"]
    edges = [{"prerequisite": "a", "dependent": "f"}, {"prerequisite": "f", "dependent": "g"}, {"prerequisite": "g", "dependent": "h"}]
    plan = {"objectives": [{"conceptId": x, "layer": "basic" if x in "abcde" else "advanced" if x == "h" else "intermediate", "teaches": f"Exclusive teaching scope for {x}", "adds": f"New capability for objective {x}", "assumes": [] if x in "abcde" else ["a"] if x == "f" else ["f"] if x == "g" else ["g"]} for x in "abcdefgh"]}
    validate_curriculum(plan, concepts, edges)


def test_relationship_review_can_only_remove_proposed_pairs():
    from learnloop.agents.expert.organization import constrain_review
    proposed = {"prerequisites": [{"prerequisite": "a", "dependent": "b"}]}
    invented = {"prerequisite": "a", "dependent": "c"}
    review = {"prerequisites": proposed["prerequisites"] + [invented], "related": []}
    result, discarded = constrain_review(review, proposed)
    assert result["prerequisites"] == proposed["prerequisites"]
    assert discarded == 1 and len(review["prerequisites"]) == 2


def test_higher_lesson_retrieval_includes_prerequisite_evidence():
    from learnloop.agents.expert.materials import source_context
    chunks = [{"id": str(i), "ordinal": i, "text": "Alignment memory layout"} for i in range(10)]
    chunks[9]["text"] = "FileAlignment = 512; SectionAlignment = 4096."
    concept = {"title": "Alignment memory layout", "summary": "Compare layouts", "sources": [{"chunkId": "0"}]}
    parent = {"sources": [{"chunkId": "9"}]}
    selected = source_context(concept, chunks, [parent])
    assert [c["id"] for c in selected[:2]] == ["0", "9"]
    assert len(selected) == 6
