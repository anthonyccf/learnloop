"""Sessions HTTP endpoints; registered by the application factory."""

import copy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from learnloop.agents.tutoring.chat import answer_chat
from learnloop.api.dependencies import ApiContext
from learnloop.core.domain import concept_state, prerequisite_block
from learnloop.core.schemas import ContinueSession, StartSession, TutorChatRequest
from learnloop.persistence.database import (
    Activity,
    Course,
    StudySession,
)
from learnloop.persistence.releases import current_material_release, get_release, pin_session
from learnloop.persistence.repository import course_graph, learner
from learnloop.runtime.events import new_run


def build_router(context: ApiContext):
    router = APIRouter(tags=["Sessions"])
    factory = context.factory
    lock_course = context.lock_course
    owned = context.owned
    owner = context.owner
    runs_for_session = context.runs_for_session
    services = context.services
    session_target = context.session_target
    session_view = context.session_view

    @router.post("/api/courses/{course_id}/sessions", status_code=202)
    def start_session(course_id: str, body: StartSession, principal=Depends(owner)):
        with factory.begin() as db:
            course = owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            state = learner(db, course_id, principal, lock=True)
            if state.version != body.expectedLearnerVersion:
                raise HTTPException(409, "Learner state changed. Refresh before starting.")
            target = body.conceptId
            existing = db.scalar(
                select(StudySession).where(
                    StudySession.course_id == course_id,
                    StudySession.owner_id == principal,
                    StudySession.status == "active",
                )
            )
            if existing:
                pin_session(db, existing)
            material_release = current_material_release(db, course_id) or get_release(db, course_id)
            graph = course_graph(
                db, course_id, existing.release_id if existing else (
                    material_release.id if material_release else None
                )
            )
            if target and target not in {c["id"] for c in graph["concepts"]}:
                current_graph = course_graph(
                    db, course_id, material_release.id if material_release else None
                )
                if existing and any(c["id"] == target for c in current_graph["concepts"]):
                    raise HTTPException(409, "End this session to study a newly published lesson.")
                raise HTTPException(404, "This lesson is not published in the selected course.")
            if existing:
                if target is None:
                    return session_view(db, existing)
                current = (
                    db.get(Activity, existing.current_activity_id)
                    if existing.current_activity_id
                    else None
                )
                runs = runs_for_session(db, existing.id)
                if current and current.status == "submitted":
                    raise HTTPException(
                        409, "Wait for your submitted answer to be checked before changing topics."
                    )
                if blocked := prerequisite_block(graph, state.evidence, target):
                    if current and current.status == "pending" and current.concept_id == target:
                        return session_view(db, existing)
                    raise HTTPException(409, blocked)
                active = [
                    r for r in runs if r.snapshot["status"] in ("queued", "running", "paused")
                ]
                if active:
                    # A model call already in progress cannot be redirected. A saved
                    # run that the worker has not started follows the lesson just chosen.
                    if any(
                        r.snapshot["status"] == "running"
                        and r.input.get("target_concept_id") != target
                        for r in active
                    ):
                        raise HTTPException(
                            409,
                            "Your tutor is already preparing a question. Try this lesson again when it is ready.",
                        )
                    for run in active:
                        if (
                            run.snapshot.get("workflow") != "next_activity"
                            or run.snapshot["status"] == "running"
                            or run.input.get("target_concept_id") == target
                        ):
                            continue
                        updated = dict(run.input)
                        updated["target_concept_id"] = target
                        updated["mixed_question_formats"] = body.mixedQuestionFormats
                        run.input = updated
                        snapshot = copy.deepcopy(run.snapshot)
                        snapshot["conceptId"] = target
                        run.snapshot = snapshot
                    return session_view(db, existing)
                if (
                    current
                    and current.status == "pending"
                    and current.concept_id == target
                    and session_target(runs) == target
                ):
                    return session_view(db, existing)
                # Preserve unanswered activities when the learner explicitly changes topics.
                pending_activity = db.scalar(
                    select(Activity).where(
                        Activity.session_id == existing.id,
                        Activity.concept_id == target,
                        Activity.status == "pending",
                    )
                )
                existing.current_activity_id = pending_activity.id if pending_activity else None
                run = new_run(
                    db,
                    course,
                    "next_activity",
                    {"session_id": existing.id, "target_concept_id": target,
                     "mixed_question_formats": body.mixedQuestionFormats},
                    target,
                )
                return session_view(db, existing)
            if not graph["concepts"]:
                raise HTTPException(409, "Publish course resources before starting a session.")
            if blocked := prerequisite_block(graph, state.evidence, target):
                raise HTTPException(409, blocked)
            if material_release is None:
                raise HTTPException(409, "Publish course resources before starting a session.")
            session = StudySession(
                course_id=course_id, owner_id=principal, release_id=material_release.id
            )
            db.add(session)
            db.flush()
            run = new_run(
                db,
                course,
                "next_activity",
                {"session_id": session.id, "target_concept_id": target,
                 "mixed_question_formats": body.mixedQuestionFormats},
                target,
            )
            return {
                "id": session.id,
                "courseId": course_id,
                "releaseId": session.release_id,
                "status": "active",
                "activity": None,
                "assessment": None,
                "runIds": [run.id],
                "targetConceptId": target,
            }

    @router.get("/api/sessions/{session_id}")
    def get_session(session_id: str, principal=Depends(owner)):
        with factory() as db:
            return session_view(db, owned(db, StudySession, session_id, principal))

    @router.post("/api/sessions/{session_id}/chat")
    def tutor_chat(session_id: str, body: TutorChatRequest, principal=Depends(owner)):
        from learnloop.runtime.events import default_template
        from learnloop.runtime.workflows import PromptConfiguredServices
        with factory() as db:
            template = default_template(db, principal, "tutor")
        return answer_chat(factory, PromptConfiguredServices(services, template), session_id, principal, body)

    @router.post("/api/sessions/{session_id}/end")
    def end_session(session_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            session = owned(db, StudySession, session_id, principal)
            lock_course(db, session.course_id)
            session.status = "ended"
            return {"id": session.id, "status": session.status}

    @router.post("/api/sessions/{session_id}/next", status_code=202)
    def next_activity(session_id: str, body: ContinueSession, principal=Depends(owner)):
        with factory.begin() as db:
            session = owned(db, StudySession, session_id, principal)
            course = lock_course(db, session.course_id)
            db.refresh(session)
            if session.status != "active":
                raise HTTPException(409, "Session has ended.")
            state = learner(db, course.id, principal, lock=True)
            if state.version != body.expectedLearnerVersion:
                raise HTTPException(409, "Learner state changed. Refresh before continuing.")
            current = (
                db.get(Activity, session.current_activity_id)
                if session.current_activity_id
                else None
            )
            if current and current.status == "pending":
                return session_view(db, session)
            if current and current.status == "submitted":
                raise HTTPException(409, "Wait for the submitted response to be assessed.")
            runs = runs_for_session(db, session.id)
            if any(
                r.snapshot["status"] in ("queued", "running", "paused")
                for r in runs
            ):
                raise HTTPException(409, "A session run is already pending.")
            latest = context.latest_activity_run(runs)
            target = latest.input.get("target_concept_id") if latest else None
            pin_session(db, session)
            graph = course_graph(db, course.id, session.release_id)
            concept = next((c for c in graph["concepts"] if c["id"] == target), None)
            if concept and concept_state(concept, state.evidence) == "demonstrated":
                # Focus lasts until the requested topic is complete. The tutor
                # then chooses the next eligible topic across the learning plan.
                target = None
            if blocked := prerequisite_block(graph, state.evidence, target):
                raise HTTPException(409, blocked)
            # Only this explicit learner action advances away from assessed work.
            session.current_activity_id = None
            run = new_run(
                db,
                course,
                "next_activity",
                {
                    "session_id": session.id,
                    "target_concept_id": target,
                    "mixed_question_formats": body.mixedQuestionFormats or bool(
                        latest and latest.input.get("mixed_question_formats")
                    ),
                    "previous_concept_id": current.concept_id if current else None,
                },
                target,
            )
            return {"runId": run.id}

    return router
