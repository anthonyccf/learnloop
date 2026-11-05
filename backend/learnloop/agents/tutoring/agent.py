"""Tutoring Agent entry point: observe evidence, select, retrieve, and assign.

Eligibility/ranking are deterministic domain policy. The Expert question bank
is used first; the model supplies a new grounded question when it is exhausted.
"""

import copy
import re

from sqlalchemy import select

from learnloop.agents.expert.materials import prepared_question
from learnloop.agents.question_review import question_review_valid, review_question
from learnloop.agents.references import refs
from learnloop.agents.rubrics import ensure_rubric
from learnloop.agents.tutoring.prompts import PLAN_PROMPT, QUESTION_PROMPT
from learnloop.core.domain import select_concept, target_difficulty
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import (
    source_ids,
    validate_sources,
)
from learnloop.core.planning import candidates
from learnloop.core.schemas import PlanChoice, Question
from learnloop.persistence.database import Activity, Course, Run, StudySession, now
from learnloop.persistence.plans import get_plan, record_revision
from learnloop.persistence.releases import pin_session
from learnloop.persistence.repository import course_graph, grounding_chunks, learner, retrieve
from learnloop.runtime.events import accept, pending, run_status, step


def run(factory, services, run_id):
    with factory.begin() as db:
        run = db.get(Run, run_id)
        session = db.get(StudySession, run.input["session_id"])
        db.scalar(select(Course).where(Course.id == session.course_id).with_for_update())
        if session.status != "active":
            run_status(db, run_id, "completed", "The learning session has ended.")
            return
        current = (
            db.get(Activity, session.current_activity_id) if session.current_activity_id else None
        )
        if current and current.status == "pending":
            run_status(
                db,
                run_id,
                "waiting_for_learner",
                "The saved activity is waiting for a learner response.",
            )
            return
        run_status(db, run_id, "running", "Tutoring is selecting the next learning activity.")
        step(
            db,
            run_id,
            "tutoring",
            "Load learner evidence",
            "Check target-level evidence and prerequisite readiness.",
            "load_learner_state",
        )
        release_id = pin_session(db, session)
        run.input = {**run.input, "release_id": release_id}
        state = learner(db, session.course_id, session.owner_id)
        target = run.input.get("target_concept_id")
        graph = copy.deepcopy(course_graph(db, session.course_id, release_id))
        plan = get_plan(db, session.course_id, session.owner_id, create=True)
        plan_version, goal = plan.version, copy.deepcopy(plan.goal)
        plan_data = copy.deepcopy(plan.data)
        review_dates = {
            c["id"]: record["reviewAt"]
            for c in graph["concepts"]
            if (record := state.evidence.get(c["id"], {}).get(target_difficulty(c), {})).get(
                "reviewAt"
            )
        }
        review_dates.update(plan_data.get("reviewDates", {}))
        options = candidates(
            graph,
            state.evidence,
            goal,
            target,
            current.concept_id if current else run.input.get("previous_concept_id"),
            review_dates,
        )
        if not options:
            run_status(
                db,
                run_id,
                "completed",
                "No eligible unmastered concept is available. Review the course map or return when review is due.",
            )
            return
        evidence_version = state.version
        course_id, owner_id = session.course_id, session.owner_id
    offered = options[:12]
    choice = services.generate(
        "Tutoring", PLAN_PROMPT, {"goal": goal, "candidates": offered}, PlanChoice
    )
    selected = next((c for c in offered if c["id"] == choice.candidateId), None)
    if not selected:
        raise ServiceError(
            "invalid_plan", "The proposed action is not an eligible planning candidate.", False
        )
    concept = next(c for c in graph["concepts"] if c["id"] == selected["conceptId"])
    difficulty = selected["difficulty"]
    with factory.begin() as db:
        step(db, run_id, "tutoring", "Choose learning action", choice.rationale, "revise_plan")
        previous = list(
            db.scalars(
                select(Activity)
                .join(StudySession, Activity.session_id == StudySession.id)
                .where(
                    StudySession.course_id == course_id,
                    StudySession.owner_id == owner_id,
                    Activity.concept_id == concept["id"],
                )
            )
        )
        prompts = [a.public["prompt"] for a in previous]
        step(
            db,
            run_id,
            "tutoring",
            "Retrieve learning sources",
            "Find published passages for an eligible concept.",
            "retrieve_evidence",
        )
    with factory() as db:
        output, passages = prepared_question(
            db, course_id, concept["id"], prompts, difficulty, release_id
        )
    question_origin = "expert" if output is not None else "tutoring"
    if output is None:
        with factory() as db:
            passages = retrieve(
                db,
                services,
                course_id,
                owner_id,
                concept["title"] + " " + concept["summary"],
                release_id=release_id,
            )
        if not passages:
            raise ServiceError(
                "no_grounding",
                "No published source passages were retrieved for this activity.",
                False,
            )
        output = services.generate(
            "Tutoring",
            QUESTION_PROMPT,
            {
                "concept": concept,
                "difficulty": difficulty,
                "previousPrompts": prompts[-12:],
                "passages": [{"chunkId": c["id"], "text": c["text"]} for c in passages],
            },
            Question,
        )
    output = ensure_rubric(services, output, passages)
    if output.difficulty != difficulty:
        raise ServiceError(
            "invalid_difficulty", "The question does not match the selected difficulty.", False
        )

    def normalize(value):
        return re.sub(r"\W+", "", value.casefold())

    if normalize(output.prompt) in {normalize(prompt) for prompt in prompts}:
        raise ServiceError(
            "duplicate_question",
            "The generated question duplicates an earlier activity. Retry to request a distinct question.",
        )
    chunk_map = {c["id"]: c for c in passages}
    # Covers both legacy Expert questions and newly generated fallback questions.
    validate_sources(output, chunk_map)
    # The catalog concept was published by the Expert. This assignment reviews
    # the actual question, not unrelated claims in its broader topic summary.
    # Match the Assessing Agent's review scope and retain commit-time source checks.
    reviewed_item = output.model_dump()
    reviewed_receipt = review_question(
        services,
        "Tutoring",
        reviewed_item,
        chunk_map,
        concept=concept,
    )
    grounding = reviewed_receipt
    with factory.begin() as db:
        # Serialize every learning mutation per course before the learner/session rows.
        db.scalar(select(Course).where(Course.id == course_id).with_for_update())
        state = learner(db, course_id, owner_id, lock=True)
        plan = get_plan(db, course_id, owner_id)
        session = db.scalar(
            select(StudySession).where(StudySession.id == session.id).with_for_update()
        )
        if state.version != evidence_version or plan.version != plan_version:
            raise ServiceError(
                "learner_changed",
                "Learner evidence changed while planning. Retry using the latest state.",
            )
        current_graph = course_graph(db, course_id, release_id)
        if current_graph != graph or (
            concept["id"] != target
            and not select_concept(current_graph, state.evidence, concept["id"])
        ):
            raise ServiceError(
                "plan_changed",
                "Course relationships changed during planning. Retry using the current graph.",
            )
        if session.status != "active":
            run_status(db, run_id, "completed", "The session ended before activity assignment.")
            return
        if (
            session.current_activity_id
            and db.get(Activity, session.current_activity_id).status == "pending"
        ):
            run_status(
                db,
                run_id,
                "waiting_for_learner",
                "An existing pending activity was retained.",
            )
            return
        current_chunks = grounding_chunks(
            db, course_id, owner_id, source_ids(reviewed_item), release_id
        )
        if not question_review_valid(reviewed_item, current_chunks, reviewed_receipt):
            raise ServiceError(
                "source_changed",
                "Course evidence changed during source review. Review it before assignment.",
                False,
            )
        references = refs(output.sources, {c["id"]: c for c in passages}, concept["id"])
        activity = Activity(
            session_id=session.id,
            concept_id=concept["id"],
            difficulty=difficulty,
            public={
                "prompt": output.prompt,
                "choices": [c.model_dump() for c in output.choices],
                "sources": references,
                "authoredBy": question_origin,
                "action": selected["action"],
                "objective": selected["objective"],
                "rationale": choice.rationale,
                "extendedTopic": grounding["status"] == "extended",
                "extensionReason": grounding.get("reason"),
            },
            private={
                "correctChoiceId": output.correctChoiceId,
                "explanation": output.explanation,
                "hint": output.hint,
                "question": output.model_dump(),
                "releaseId": release_id,
                "grounding": grounding,
                "assignedAt": now().isoformat(),
            },
        )
        db.add(activity)
        db.flush()
        session.current_activity_id = activity.id
        if selected["action"] == "reassess":
            review_dates.pop(concept["id"], None)
        data = {
            **plan_data,
            "learnerVersion": state.version,
            "activityIds": list(dict.fromkeys([*plan_data.get("activityIds", []), activity.id])),
            "reviewDates": review_dates,
            "candidates": options,
            "selected": selected,
            "reason": choice.rationale,
        }
        record_revision(
            db,
            plan,
            f"run:{run_id}",
            {"runId": run_id, "learnerVersion": evidence_version},
            goal,
            data,
        )
        pending(db, run_id, "activity")
        accept(db, run_id, "activity")
        step(
            db,
            run_id,
            "tutoring",
            "Activity ready",
            "An Expert-approved extended topic is ready for the learner."
            if grounding["status"] == "extended"
            else "A source-grounded question is ready for the learner.",
            "assign_activity",
            "completed",
            references=references,
            artifacts=[
                {
                    "id": activity.id,
                    "kind": "activity",
                    "label": "Multiple-choice question",
                    "status": "committed",
                }
            ],
        )
        run_status(
            db,
            run_id,
            "waiting_for_learner",
            "Waiting for the learner to answer. No agent needs to run while they think.",
        )
