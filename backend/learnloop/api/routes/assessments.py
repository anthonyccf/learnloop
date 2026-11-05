"""Assessments HTTP endpoints; registered by the application factory."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from learnloop.api.dependencies import ApiContext
from learnloop.core.schemas import SubmitAnswer
from learnloop.persistence.database import (
    Activity,
    Course,
    ResponseDetail,
    Run,
    StudySession,
    Submission,
    now,
)
from learnloop.persistence.repository import learner
from learnloop.runtime.events import new_run


def build_router(context: ApiContext):
    router = APIRouter(tags=["Assessments"])
    factory = context.factory
    lock_course = context.lock_course
    owned = context.owned
    owner = context.owner

    @router.post("/api/activities/{activity_id}/present")
    def present(activity_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            activity = owned(db, Activity, activity_id, principal)
            session = db.get(StudySession, activity.session_id)
            lock_course(db, session.course_id)
            db.refresh(activity)
            db.refresh(session)
            if (
                activity.status != "pending"
                or session.status != "active"
                or session.current_activity_id != activity.id
            ):
                raise HTTPException(409, "This activity is no longer awaiting an answer.")
            if not activity.private.get("presentedAt"):
                activity.private = {**activity.private, "presentedAt": now().isoformat()}
            return {"activityId": activity.id, "presentedAt": activity.private["presentedAt"]}

    @router.post("/api/activities/{activity_id}/hint")
    def hint(activity_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            activity = owned(db, Activity, activity_id, principal)
            session = db.get(StudySession, activity.session_id)
            lock_course(db, session.course_id)
            db.refresh(activity)
            db.refresh(session)
            if (
                activity.status != "pending"
                or session.status != "active"
                or session.current_activity_id != activity.id
            ):
                raise HTTPException(409, "This activity is no longer awaiting an answer.")
            activity.hinted = True
            return {
                "activityId": activity.id,
                "hintUsed": True,
                "hint": activity.private["hint"],
            }

    @router.post("/api/activities/{activity_id}/responses", status_code=202)
    def answer(activity_id: str, body: SubmitAnswer, principal=Depends(owner)):
        with factory.begin() as db:
            activity = owned(db, Activity, activity_id, principal)
            session = db.get(StudySession, activity.session_id)
            course = lock_course(db, session.course_id)
            db.refresh(activity)
            db.refresh(session)
            existing = db.scalar(
                select(Submission).where(
                    Submission.owner_id == principal,
                    Submission.operation_id == body.operationId,
                )
            )
            if existing:
                detail = db.get(ResponseDetail, existing.id)
                if (
                    existing.activity_id,
                    existing.choice_id,
                    existing.expected_version,
                ) != (activity_id, body.choiceId, body.expectedLearnerVersion) or (
                    detail.reasoning if detail else None
                ) != body.reasoning:
                    raise HTTPException(409, "Operation ID already belongs to a different request.")
                run = next(
                    r
                    for r in db.scalars(select(Run).where(Run.course_id == course.id))
                    if r.input.get("submission_id") == existing.id
                )
                return {"submissionId": existing.id, "runId": run.id}
            if (
                session.status != "active"
                or activity.status != "pending"
                or session.current_activity_id != activity.id
            ):
                raise HTTPException(409, "This activity is no longer awaiting an answer.")
            state = learner(db, course.id, principal, lock=True)
            if state.version != body.expectedLearnerVersion:
                raise HTTPException(409, "Learner state changed. Refresh before submitting.")
            if body.choiceId not in {c["id"] for c in activity.public["choices"]}:
                raise HTTPException(422, "Choose one of the provided options.")
            submission = Submission(
                activity_id=activity.id,
                owner_id=principal,
                operation_id=body.operationId,
                expected_version=body.expectedLearnerVersion,
                choice_id=body.choiceId,
            )
            db.add(submission)
            db.flush()
            submitted_at = now()
            start = activity.private.get("presentedAt") or activity.private.get("assignedAt")
            elapsed = (
                max(0, int((submitted_at - datetime.fromisoformat(start)).total_seconds() * 1000))
                if start
                else None
            )
            db.add(
                ResponseDetail(
                    submission_id=submission.id,
                    reasoning=body.reasoning,
                    timing={
                        "startedAt": start,
                        "submittedAt": submitted_at.isoformat(),
                        "responseTimeMs": elapsed,
                        "basis": "presentation"
                        if activity.private.get("presentedAt")
                        else "assignment"
                        if start
                        else "unavailable",
                    },
                )
            )
            activity.status = "submitted"
            run = new_run(
                db,
                course,
                "assessment",
                {"session_id": session.id, "submission_id": submission.id},
                activity.concept_id,
            )
            return {"submissionId": submission.id, "runId": run.id}

    @router.get("/api/submissions/{submission_id}")
    def get_submission(submission_id: str, principal=Depends(owner)):
        with factory() as db:
            submission = owned(db, Submission, submission_id, principal)
            return {
                "id": submission.id,
                "activityId": submission.activity_id,
                "choiceId": submission.choice_id,
                "status": "assessed" if submission.assessment else "pending",
                "assessment": submission.assessment or None,
            }

    @router.get("/api/courses/{course_id}/assessments")
    def assessment_history(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            rows = db.execute(
                select(Submission, Activity)
                .join(Activity, Submission.activity_id == Activity.id)
                .join(StudySession, Activity.session_id == StudySession.id)
                .where(
                    StudySession.course_id == course_id,
                    Submission.owner_id == principal,
                )
                .order_by(Submission.created_at)
            )
            return [
                {
                    "id": s.id,
                    "activityId": a.id,
                    "conceptId": a.concept_id,
                    "difficulty": a.difficulty,
                    "choiceId": s.choice_id,
                    "at": s.created_at.isoformat(),
                    "assessment": s.assessment or None,
                }
                for s, a in rows
            ]

    return router
