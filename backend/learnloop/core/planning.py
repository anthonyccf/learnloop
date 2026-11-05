"""Bounded educational actions ranked from authoritative learner evidence."""

from datetime import UTC, datetime

from learnloop.core.domain import (
    concept_state,
    select_concept,
    select_difficulty,
    target_difficulty,
)
from learnloop.core.schemas import LearningGoal


def candidates(graph, evidence, goal=None, focus=None, previous=None, review_dates=None):
    goal = goal or LearningGoal().model_dump()
    by_id = {c["id"]: c for c in graph.get("concepts", [])}
    requested = {focus} if focus else set(goal.get("conceptIds", []))
    allowed = set(requested)
    ancestors = set()

    def visit(id):
        for edge in graph.get("prerequisites", []):
            parent = edge["prerequisite"]
            if edge["dependent"] == id and parent not in ancestors:
                ancestors.add(parent)
                visit(parent)

    for id in requested:
        visit(id)
    allowed.update(ancestors)
    previous_concept = by_id.get(previous)
    advanced = previous_concept and concept_state(previous_concept, evidence) == "demonstrated"
    related = {
        edge["second"] if edge["first"] == previous else edge["first"]
        for edge in graph.get("related", [])
        if previous in (edge["first"], edge["second"])
    }
    result = []
    for concept in by_id.values():
        id = concept["id"]
        # A direct quiz launch is the learner's choice to challenge this topic.
        if focus and id != focus:
            continue
        if requested and id not in allowed:
            continue
        if id != focus and not select_concept(graph, evidence, id):
            continue
        state = concept_state(concept, evidence)
        scheduled = (review_dates or {}).get(id)
        scheduled_due = bool(scheduled and datetime.fromisoformat(scheduled) <= datetime.now(UTC))
        if state == "demonstrated" and id != focus and not scheduled_due:
            continue
        level = select_difficulty(concept, evidence)
        records = evidence.get(id, {})
        latest = max(records.values(), key=lambda r: r.get("lastAssessedAt", ""), default={})
        outcome = latest.get("lastOutcome", {})
        weak = bool(
            outcome
            and (
                not outcome.get("correct")
                or outcome.get("hinted")
                or outcome.get("uncertain")
                or outcome.get("partial")
            )
        )
        need = {"unassessed": 0.6, "developing": 1.0, "review_due": 0.8, "demonstrated": 0.1}[state]
        uncertainty = 1.0 if outcome.get("uncertain") else 0.5 if state == "unassessed" else 0.0
        urgency = 1.0 if state == "review_due" else 0.0
        if scheduled_due:
            urgency = 1.0
            level = target_difficulty(concept)
        performance = 1.0 if weak else 0.5 if latest.get("attempts") else 0.0
        goal_match = 1.0 if id in requested else 0.7 if id in ancestors else 0.0
        words = set(goal.get("description", "").lower().split())
        if len(words & set((concept["title"] + " " + concept["summary"]).lower().split())) >= 2:
            goal_match = max(goal_match, 0.4)
        action = "practice"
        if state == "review_due" or urgency:
            action = "reassess"
        elif id in ancestors:
            action = "revisit_prerequisite"
        elif weak and level != target_difficulty(concept):
            action = "adjust_difficulty"
        elif weak:
            action = "remediate"
        elif advanced and id in related:
            action = "advance_related"
        elif state == "unassessed":
            action = "introduce"
        factors = {
            "need": need,
            "uncertainty": uncertainty,
            "urgency": urgency,
            "recentPerformance": performance,
            "goalMatch": goal_match,
        }
        score = round(
            3 * need
            + uncertainty
            + 4 * urgency
            + 2 * performance
            + 2 * goal_match
            + (0.5 if advanced and id in related else 0),
            3,
        )
        result.append(
            {
                "id": f"{id}|{action}|{level}",
                "conceptId": id,
                "title": concept["title"],
                "objective": concept["summary"],
                "action": action,
                "difficulty": level,
                "score": score,
                "factors": factors,
                "evidenceIds": latest.get("assessmentIds", [])[-8:],
            }
        )
    return sorted(result, key=lambda c: -c["score"])
