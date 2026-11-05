import copy
from datetime import UTC, datetime, timedelta

import pytest

from learnloop.core.domain import assess_evidence, select_difficulty

AT = datetime(2026, 10, 23, tzinfo=UTC)


def assess(record, id, correct=False, hinted=False, uncertain=False, at=AT):
    return assess_evidence(record, id, correct, hinted, uncertain, at)[1]


def demonstrated():
    return assess(assess(None, "s1", True), "s2", True)


def test_two_distinct_certain_independent_failures_confirm_weakness_and_keep_history():
    original = demonstrated()
    frozen = copy.deepcopy(original)
    first = assess(original, "f1")
    second = assess(first, "f2")
    assert first["state"] == "review_due" and first["lastTransition"]["outcome"] == "contradiction"
    assert (
        second["state"] == "developing"
        and second["lastTransition"]["outcome"] == "confirmed_weakness"
    )
    assert second["confirmedWeakness"]["activityIds"] == ["f1", "f2"]
    assert second["independentHistoryActivityIds"] == ["s1", "s2"]
    assert second["independentActivityIds"] == [] and "reviewAt" not in second
    assert original == frozen
    assert select_difficulty({"id": "c"}, {"c": {"intermediate": first}}) == "intermediate"
    assert select_difficulty({"id": "c"}, {"c": {"intermediate": second}}) == "basic"


@pytest.mark.parametrize(
    "correct,hinted,uncertain",
    [
        (False, False, True),
        (True, False, True),
        (False, True, False),
        (True, True, False),
        (True, False, False),
    ],
)
def test_uncertainty_assistance_or_success_interrupts_failure_confirmation(
    correct, hinted, uncertain
):
    first = assess(demonstrated(), "f1")
    interrupted = assess(first, "interruption", correct, hinted, uncertain)
    result = assess(interrupted, "f2")
    assert not result.get("confirmedWeakness")
    assert result["consecutiveFailureActivityIds"] == ["f2"]


def test_repeated_failure_activity_cannot_confirm_and_unassessed_errors_do_not_downgrade_mastery():
    first = assess(demonstrated(), "f1")
    repeated = assess(first, "f1")
    assert repeated["state"] == "review_due" and repeated["consecutiveFailureActivityIds"] == ["f1"]
    assert not repeated.get("confirmedWeakness")
    initial = assess(assess(None, "f1"), "f2")
    assert initial["state"] == "developing" and not initial.get("confirmedWeakness")


def test_recovery_requires_fresh_independent_evidence_and_keeps_weakness_episodes():
    failed = assess(assess(demonstrated(), "f1"), "f2")
    one = assess(failed, "r1", True)
    assert one["state"] == "developing" and one["confirmedWeakness"]["status"] == "active"
    assert one["lastTransition"]["outcome"] == "recovery_progress"
    assisted = assess(one, "hinted", True, True)
    assert assisted["state"] == "developing" and assisted["independentActivityIds"] == ["r1"]
    recovered = assess(assisted, "r2", True)
    assert (
        recovered["state"] == "demonstrated"
        and recovered["confirmedWeakness"]["status"] == "resolved"
    )
    assert recovered["independentHistoryActivityIds"] == ["s1", "s2", "r1", "r2"]
    assert recovered["weaknessHistory"][0]["resolvedBy"] == "r2"
    again = assess(assess(recovered, "f3"), "f4")
    assert (
        len(again["weaknessHistory"]) == 2
        and again["weaknessHistory"][0] == recovered["weaknessHistory"][0]
    )


def test_expired_or_legacy_review_never_invents_failure_evidence():
    old = {
        "state": "review_due",
        "attempts": 4,
        "assisted": 0,
        "independentActivityIds": [],
        "lastOutcome": {"correct": False, "hinted": False, "uncertain": False},
    }
    first = assess(old, "new-f1")
    assert first["state"] == "review_due" and not first.get("confirmedWeakness")
    due = assess(demonstrated(), "r1", True, at=AT + timedelta(days=8))
    assert due["state"] == "developing" and not due.get("confirmedWeakness")
    assert due["independentHistoryActivityIds"] == ["s1", "s2", "r1"]
