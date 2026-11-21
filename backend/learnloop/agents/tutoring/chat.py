"""Answer lesson questions with public teaching context and preserve hint policy."""

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from learnloop.agents.expert.materials import public_materials
from learnloop.agents.tutoring.prompts import CHAT_PROMPT
from learnloop.core.schemas import TutorChatReply
from learnloop.persistence.database import Activity, Course, StudySession
from learnloop.persistence.learner_memory import learner_memory, record_tutor_observation
from learnloop.persistence.releases import pin_session, released_chunks, released_documents
from learnloop.persistence.repository import course_graph, learner, public_activity


def answer_chat(factory, services, session_id, owner_id, body):
    with factory.begin() as db:
        session = db.get(StudySession, session_id)
        if not session or session.owner_id != owner_id:
            raise HTTPException(404, "Resource not found.")
        if session.status != "active":
            raise HTTPException(409, "Start or resume a session before messaging your tutor.")
        pin_session(db, session)
        activity = (
            db.get(Activity, session.current_activity_id) if session.current_activity_id else None
        )
        if not activity or activity.id != body.activityId:
            raise HTTPException(
                409, "Your learning step changed. Refresh before sending this message."
            )
        if activity.status == "submitted":
            raise HTTPException(
                409, "Wait for your answer to be reviewed before messaging your tutor."
            )
        concept = next(
            (
                c
                for c in course_graph(db, session.course_id, session.release_id)["concepts"]
                if c["id"] == activity.concept_id
            ),
            None,
        )
        if not concept:
            raise HTTPException(409, "This lesson is no longer published.")
        lesson = None
        sources = []
        for doc in released_documents(db, session.course_id, session.release_id):
            chunks = [
                SimpleNamespace(**c)
                for c in released_chunks(db, session.course_id, session.release_id, extracted_only=True).values()
                if c["document_id"] == doc.id
            ]
            pages = {chunk.id: chunk.page for chunk in chunks}
            source_chunks = {chunk.id: {"text": chunk.text} for chunk in chunks}
            material = next(
                (
                    m
                    for m in public_materials(doc, pages, source_chunks)
                    if m["conceptId"] == activity.concept_id
                ),
                None,
            )
            if material:
                lesson = material.get("lessonsByDifficulty", {}).get(
                    activity.difficulty, material["lesson"]
                )
                sources = material.get("sourcesByDifficulty", {}).get(
                    activity.difficulty, material["sources"]
                )
                break
        if lesson is None:
            raise HTTPException(
                409, "This lesson needs source review before tutoring. Prepare its materials again."
            )
        course_id, activity_id, initial_status = session.course_id, activity.id, activity.status
        memory = learner_memory(db, learner(db, course_id, owner_id), session.release_id, [concept])
        context = {
            "concept": concept,
            "lesson": lesson,
            "activity": public_activity(activity),
            "assessment_pending": initial_status == "pending",
            "history": [turn.model_dump() for turn in body.history],
            "message": body.message,
            "learnerMemory": memory[concept["id"]],
        }

    # No database transaction stays open during the model request.
    reply = services.generate("Tutoring", CHAT_PROMPT, context, TutorChatReply)
    with factory.begin() as db:
        db.scalar(select(Course).where(Course.id == course_id).with_for_update())
        session = db.get(StudySession, session_id)
        activity = db.get(Activity, activity_id)
        if (
            session.status != "active"
            or session.current_activity_id != activity_id
            or activity.status != initial_status
        ):
            raise HTTPException(
                409, "Your learning step changed while the tutor replied. Refresh and try again."
            )
        if activity.status == "pending":
            activity.hinted = True
        record_tutor_observation(activity, body.message, reply.observation)
        return {
            "reply": reply.text,
            "sources": sources,
            "assistanceUsed": activity.status == "pending",
        }
