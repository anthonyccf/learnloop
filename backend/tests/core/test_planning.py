from learnloop.core.planning import candidates


def graph():
    return {
        "concepts": [
            {
                "id": id,
                "title": id,
                "summary": "A supported learning objective.",
                "targetDifficulty": "intermediate",
            }
            for id in "abcd"
        ],
        "prerequisites": [{"prerequisite": "a", "dependent": "b"}],
        "related": [{"first": "a", "second": "c"}],
    }


def test_goal_routes_to_unmet_prerequisite_and_excludes_unrelated_concepts():
    choices = candidates(graph(), {}, {"description": "Understand b", "conceptIds": ["b"]})
    assert [(c["conceptId"], c["action"]) for c in choices] == [("a", "revisit_prerequisite")]
    evidence = {"a": {"intermediate": {"state": "demonstrated"}}}
    assert candidates(graph(), evidence, {"conceptIds": ["b"]})[0]["conceptId"] == "b"


def test_policy_scores_uncertainty_review_urgency_performance_and_related_advancement():
    evidence = {
        "a": {"intermediate": {"state": "demonstrated"}},
        "c": {"intermediate": {"state": "review_due"}},
        "d": {
            "intermediate": {
                "state": "developing",
                "attempts": 1,
                "lastAssessedAt": "2026-01-01",
                "lastOutcome": {"correct": False, "uncertain": True},
            }
        },
    }
    choices = candidates(graph(), evidence, previous="a")
    assert choices[0]["conceptId"] == "c" and choices[0]["action"] == "reassess"
    weak = next(c for c in choices if c["conceptId"] == "d")
    assert weak["action"] == "adjust_difficulty" and weak["difficulty"] == "basic"
    assert weak["factors"]["uncertainty"] == weak["factors"]["recentPerformance"] == 1
    evidence.pop("c")
    assert (
        next(c for c in candidates(graph(), evidence, previous="a") if c["conceptId"] == "c")[
            "action"
        ]
        == "advance_related"
    )


def test_explicit_focus_allows_challenging_a_topic_with_unmet_prerequisites():
    choices = candidates(graph(), {}, focus="b")
    assert [(c["conceptId"], c["action"]) for c in choices] == [("b", "introduce")]
    assert candidates(graph(), {}, focus="unknown") == []


def test_scheduled_reviews_are_observed():
    assert (
        candidates(graph(), {}, review_dates={"d": "2020-01-01T00:00:00+00:00"})[0]["conceptId"]
        == "d"
    )
