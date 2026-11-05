from datetime import UTC, datetime, timedelta

from learnloop.core.domain import assess_evidence, concept_state, select_concept, select_difficulty


def test_curriculum_target_controls_mastery_and_readiness_without_relabelling_evidence():
    import copy

    from learnloop.core.domain import target_difficulty

    parent = {"id": "a", "targetDifficulty": "intermediate", "curriculum": {"layer": "basic"}}
    child = {"id": "b", "curriculum": {"layer": "advanced"}}
    evidence = {"a": {"basic": {"state": "demonstrated"}, "intermediate": {"state": "developing"}}}
    before = copy.deepcopy(evidence)
    assert target_difficulty(parent) == "basic"
    assert target_difficulty(child) == "advanced"
    assert concept_state(parent, evidence) == "demonstrated"
    assert select_difficulty(parent, {}) == "basic"
    graph = {"concepts": [parent, child], "prerequisites": [{"prerequisite": "a", "dependent": "b"}]}
    assert select_concept(graph, evidence, "b")["id"] == "b"
    assert concept_state(child, {"b": {"basic": {"state": "demonstrated"}}}) == "unassessed"
    assert evidence == before


def test_prerequisites_and_overall_status_use_each_concepts_own_target():
    parent = {"id": "a", "targetDifficulty": "advanced"}
    child = {"id": "b", "targetDifficulty": "basic"}
    graph = {
        "concepts": [parent, child],
        "prerequisites": [{"prerequisite": "a", "dependent": "b"}],
    }
    evidence = {
        "a": {"basic": {"state": "demonstrated"}, "intermediate": {"state": "demonstrated"}}
    }
    assert concept_state(parent, evidence) == "unassessed"
    assert select_concept(graph, evidence, "b") is None
    evidence["a"]["advanced"] = {"state": "demonstrated"}
    assert select_concept(graph, evidence)["id"] == "b"
    evidence["b"] = {"basic": {"state": "demonstrated"}}
    assert select_concept(graph, evidence) is None


def test_difficulty_steps_down_after_assistance_and_back_up_after_independent_evidence():
    concept = {"id": "a", "targetDifficulty": "advanced"}
    evidence = {"a": {}}
    at = datetime.now(UTC)
    assert select_difficulty(concept, evidence) == "advanced"
    for index, (level, correct, hinted) in enumerate(
        [
            ("advanced", False, False),
            ("intermediate", True, True),
            ("basic", True, False),
            ("basic", True, False),
            ("intermediate", True, False),
            ("intermediate", True, False),
        ]
    ):
        _, record = assess_evidence(
            evidence["a"].get(level),
            str(index),
            correct,
            hinted,
            False,
            at + timedelta(seconds=index),
        )
        evidence["a"][level] = record
        assert (
            select_difficulty(concept, evidence)
            == ["intermediate", "basic", "basic", "intermediate", "intermediate", "advanced"][index]
        )
    assert concept_state(concept, evidence) == "developing"


def test_due_review_returns_to_target_and_legacy_evidence_uses_safe_default():
    concept = {"id": "a", "targetDifficulty": "advanced"}
    evidence = {
        "a": {"advanced": {"state": "demonstrated", "reviewAt": "2020-01-01T00:00:00+00:00"}}
    }
    assert select_difficulty(concept, evidence) == "advanced"
    assert concept_state(concept, evidence) == "review_due"
    assert (
        select_difficulty({"id": "a"}, {"a": {"intermediate": {"state": "developing"}}})
        == "intermediate"
    )
