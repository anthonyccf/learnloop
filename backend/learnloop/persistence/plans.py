"""Plan snapshots and immutable revisions; caller holds the course lock for writes."""

import copy

from sqlalchemy import select

from learnloop.core.schemas import LearningGoal
from learnloop.persistence.database import LearningPlan, PlanRevision


def get_plan(db, course_id, owner_id, create=False):
    plan = db.scalar(
        select(LearningPlan).where(
            LearningPlan.course_id == course_id, LearningPlan.owner_id == owner_id
        )
    )
    if not plan and create:
        plan = LearningPlan(
            course_id=course_id,
            owner_id=owner_id,
            goal=LearningGoal().model_dump(),
            data={},
            version=0,
        )
        db.add(plan)
        db.flush()
    return plan


def public_plan(plan):
    return {
        "version": plan.version if plan else 0,
        "goal": copy.deepcopy(plan.goal) if plan else LearningGoal().model_dump(),
        **(copy.deepcopy(plan.data) if plan else {}),
    }


def record_revision(db, plan, operation_id, request, goal, data):
    plan.goal = copy.deepcopy(goal)
    plan.data = copy.deepcopy(data)
    plan.version += 1
    snapshot = public_plan(plan)
    db.add(
        PlanRevision(
            plan_id=plan.id,
            owner_id=plan.owner_id,
            operation_id=operation_id,
            version=plan.version,
            request=copy.deepcopy(request),
            snapshot=snapshot,
        )
    )
    return snapshot
