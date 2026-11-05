"""Owner-scoped, idempotent goal and plan revision API."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from learnloop.api.dependencies import ApiContext
from learnloop.core.domain import select_concept
from learnloop.core.planning import candidates
from learnloop.core.schemas import RevisePlan
from learnloop.persistence.database import Activity, Course, PlanRevision, StudySession
from learnloop.persistence.plans import get_plan, public_plan, record_revision
from learnloop.persistence.repository import course_graph, learner


def build_router(context: ApiContext):
    router = APIRouter(tags=["Learning plans"])

    @router.get("/api/courses/{course_id}/plan")
    def get(course_id: str, principal=Depends(context.owner)):
        with context.factory() as db:
            context.owned(db, Course, course_id, principal)
            plan = get_plan(db, course_id, principal)
            state = learner(db, course_id, principal)
            view = public_plan(plan)
            view["stale"] = view.get("learnerVersion") != state.version
            return view

    @router.post("/api/courses/{course_id}/plan/revise")
    def revise(course_id: str, body: RevisePlan, principal=Depends(context.owner)):
        with context.factory.begin() as db:
            context.owned(db, Course, course_id, principal)
            context.lock_course(db, course_id)
            plan = get_plan(db, course_id, principal, create=True)
            prior = db.scalar(
                select(PlanRevision).where(
                    PlanRevision.owner_id == principal,
                    PlanRevision.operation_id == body.operationId,
                )
            )
            if prior:
                if prior.plan_id != plan.id or prior.request != body.model_dump():
                    raise HTTPException(
                        409, "Operation ID already belongs to a different plan revision."
                    )
                return prior.snapshot
            state = learner(db, course_id, principal, lock=True)
            if (
                plan.version != body.expectedPlanVersion
                or state.version != body.expectedLearnerVersion
            ):
                raise HTTPException(
                    409, "Plan or learner evidence changed. Refresh before revising."
                )
            graph = course_graph(db, course_id)
            ids = {c["id"] for c in graph["concepts"]}
            if not set(body.goal.conceptIds) <= ids or len(set(body.goal.conceptIds)) != len(
                body.goal.conceptIds
            ):
                raise HTTPException(
                    422, "Goal concepts must be distinct published concepts in this course."
                )
            if len(set(body.activityIds)) != len(body.activityIds):
                raise HTTPException(422, "Plan activity references must be distinct.")
            for id in body.activityIds:
                activity = db.get(Activity, id)
                session = db.get(StudySession, activity.session_id) if activity else None
                if not session or session.owner_id != principal or session.course_id != course_id:
                    raise HTTPException(404, "A referenced activity is unavailable in this course.")
                if activity.concept_id not in ids or not select_concept(
                    graph, state.evidence, activity.concept_id
                ):
                    raise HTTPException(
                        409, "A referenced activity has unmet prerequisites or unpublished content."
                    )
            dates = {}
            for item in body.reviewDates:
                try:
                    parsed = datetime.fromisoformat(item.reviewAt)
                    if parsed.tzinfo is None or parsed.utcoffset() is None:
                        raise ValueError()
                except ValueError:
                    raise HTTPException(
                        422, "Review dates require a timezone-aware ISO timestamp."
                    ) from None
                if item.conceptId not in ids or item.conceptId in dates:
                    raise HTTPException(
                        422, "Review dates must refer to distinct published course concepts."
                    )
                dates[item.conceptId] = parsed.isoformat()
            options = candidates(graph, state.evidence, body.goal.model_dump(), review_dates=dates)
            data = {
                "learnerVersion": state.version,
                "activityIds": body.activityIds,
                "reviewDates": dates,
                "candidates": options,
                "selected": None,
                "reason": "Learner revised the goal and schedule.",
            }
            return record_revision(
                db, plan, body.operationId, body.model_dump(), body.goal.model_dump(), data
            )

    return router
