"""Shared ownership checks and session projections for HTTP route groups."""

import secrets
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from learnloop.core.planning import candidates
from learnloop.persistence.database import (
    Activity,
    Course,
    Run,
    StudySession,
    Submission,
)
from learnloop.persistence.plans import get_plan, public_plan
from learnloop.persistence.repository import course_graph, learner, public_activity

bearer = HTTPBearer(auto_error=False)


@dataclass
class ApiContext:
    settings: Any
    factory: Any
    services: Any

    def owner(self, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        token = self.settings.api_token.get_secret_value()
        if (
            not token
            or credentials is None
            or (not secrets.compare_digest(credentials.credentials, token))
        ):
            raise HTTPException(
                401,
                "A valid backend bearer token is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return self.settings.local_owner_id

    def owned(self, db, model, id, owner_id):
        item = db.get(model, id)
        if not item:
            raise HTTPException(404, "Resource not found.")
        if model is Course or hasattr(item, "owner_id"):
            valid = item.owner_id == owner_id
        else:
            course_id = (
                item.course_id
                if hasattr(item, "course_id")
                else db.get(StudySession, item.session_id).course_id
            )
            valid = db.get(Course, course_id).owner_id == owner_id
        if not valid:
            raise HTTPException(404, "Resource not found.")
        return item

    def lock_course(self, db, course_id):
        return db.scalar(select(Course).where(Course.id == course_id).with_for_update())

    def runs_for_session(self, db, session_id):
        session = db.get(StudySession, session_id)
        return [
            run
            for run in db.scalars(select(Run).where(Run.course_id == session.course_id))
            if run.input.get("session_id") == session_id
        ]

    def session_target(self, runs):
        focused = [r for r in runs if r.snapshot["workflow"] == "next_activity"]
        if not focused:
            return None
        latest = max(
            focused,
            key=lambda r: (
                r.input.get("_started_at")
                or next((e["at"] for e in r.snapshot.get("events", [])), "")
            ),
        )
        return latest.input.get("target_concept_id")

    def session_view(self, db, session):
        activity = (
            db.get(Activity, session.current_activity_id) if session.current_activity_id else None
        )
        submission = (
            db.scalar(select(Submission).where(Submission.activity_id == activity.id))
            if activity
            else None
        )
        runs = self.runs_for_session(db, session.id)
        target = self.session_target(runs)
        plan = get_plan(db, session.course_id, session.owner_id)
        notice = None
        if (
            not activity
            and (not any((r.snapshot["status"] in ("queued", "running", "paused") for r in runs)))
            and (
                not candidates(
                    course_graph(db, session.course_id, session.release_id),
                    learner(db, session.course_id, session.owner_id).evidence,
                    plan.goal if plan else None,
                    target,
                    review_dates=plan.data.get("reviewDates") if plan else None,
                )
            )
        ):
            notice = "No further eligible questions are available right now. Review your progress or return when review is due."
        return {
            "id": session.id,
            "courseId": session.course_id,
            "releaseId": session.release_id,
            "status": session.status,
            "activity": public_activity(activity),
            "assessment": submission.assessment if submission and submission.assessment else None,
            "selectedChoiceId": submission.choice_id if submission else None,
            "notice": notice,
            "targetConceptId": target,
            "runIds": [run.id for run in runs],
            "plan": public_plan(plan),
        }
