"""Tutoring Agent entry point: observe evidence, select, retrieve, and assign.

Eligibility/ranking are deterministic domain policy. The Expert question bank
is used first; the model supplies a new grounded question when it is exhausted.
"""

import copy

from sqlalchemy import select

from learnloop.agents.expert.materials import prepared_question
from learnloop.agents.expert.questions import generate_question, saved_question
from learnloop.agents.grounding import review_grounding
from learnloop.agents.references import refs
from learnloop.agents.rubrics import ensure_rubric
from learnloop.agents.tutoring.prompts import PLAN_PROMPT
from learnloop.core.domain import prerequisite_block, select_concept, target_difficulty
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import (
    grounding_valid,
    source_ids,
)
from learnloop.core.planning import candidates
from learnloop.core.question_formats import public_prompt
from learnloop.core.schemas import PlanChoice, Question
from learnloop.persistence.database import Activity, Course, Run, StudySession, now
from learnloop.persistence.learner_memory import learner_memory
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
        mixed_formats = run.input.get("mixed_question_formats")
        graph = copy.deepcopy(course_graph(db, session.course_id, release_id))
        if blocked := prerequisite_block(graph, state.evidence, target):
            raise ServiceError(blocked["code"], blocked["message"], False, blocked)
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
        memory = learner_memory(db, state, release_id, graph["concepts"])
        options = candidates(
            graph,
            state.evidence,
            goal,
            target,
            current.concept_id if current else run.input.get("previous_concept_id"),
            review_dates,
            memory=memory,
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
        "Tutoring",
        PLAN_PROMPT,
        {
            "goal": goal,
            "candidates": offered,
            "learnerMemory": {
                c["conceptId"]: memory[c["conceptId"]] for c in offered
            },
        },
        PlanChoice,
    )
    selected = next((c for c in offered if c["id"] == choice.candidateId), None)
    if not selected:
        raise ServiceError(
            "invalid_plan", "The proposed action is not an eligible planning candidate.", False
        )
    concept = next(c for c in graph["concepts"] if c["id"] == selected["conceptId"])
    difficulty = selected["difficulty"]
    gap = memory[concept["id"]]["gap"]
    memory_target = None
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
        question_format = "single_answer"
        if mixed_formats and difficulty == "advanced":
            question_format = "open"
        elif mixed_formats and difficulty == "intermediate":
            used = sum(a.public.get("format") in ("multiple_answer", "fill_in") for a in previous)
            question_format = ("multiple_answer", "fill_in")[used % 2]
        private_prompts = {a.public["prompt"] for a in previous if a.private.get("memoryTarget")}
        if gap:
            target_ref = {key: gap[key] for key in ("id", "activityId", "assessmentId") if key in gap}
            if not any(a.private.get("memoryTarget") == target_ref for a in previous):
                memory_target = target_ref
        step(
            db,
            run_id,
            "tutoring",
            "Retrieve learning sources",
            "Find published passages for an eligible concept.",
            "retrieve_evidence",
        )
    reviewed_receipt = None
    on_demand = False
    with factory() as db:
        output, passages = None, []
        if question_format == "single_answer":
            output, passages = prepared_question(
                db, course_id, concept["id"], prompts, difficulty, release_id
            )
        if output is None:
            on_demand = True
            output, passages, reviewed_receipt = saved_question(
                db, course_id, release_id, concept["id"], difficulty, prompts, question_format
            )
    if output is None or memory_target:
        try:
            with factory() as db:
                retrieved = retrieve(
                    db,
                    services,
                    course_id,
                    owner_id,
                    concept["title"] + " " + concept["summary"],
                    release_id=release_id,
                )
            output, reviewed_receipt = generate_question(
                services, concept, difficulty, prompts, retrieved,
                diagnostic=gap["summary"] if memory_target else None,
                private_prompts=private_prompts,
                question_format=question_format,
            )
            passages = retrieved
            on_demand = True
        except ServiceError:
            if output is None and question_format != "single_answer":
                with factory() as db:
                    output, passages = prepared_question(
                        db, course_id, concept["id"], prompts, difficulty, release_id
                    )
                    if output is not None:
                        on_demand = False
                    else:
                        output, passages, reviewed_receipt = saved_question(
                            db, course_id, release_id, concept["id"], difficulty, prompts
                        )
            if output is None or (not memory_target and question_format == "single_answer"):
                raise
            # A verified general question can still be used if the private probe fails.
            memory_target = None
    if reviewed_receipt is None:
        output = ensure_rubric(services, output, passages)
        reviewed_receipt = review_grounding(
            services, "Tutoring", output, {c["id"]: c for c in passages}
        )
    reviewed_item = output.model_dump()
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
        if blocked := prerequisite_block(current_graph, state.evidence, concept["id"]):
            raise ServiceError(blocked["code"], blocked["message"], False, blocked)
        if current_graph != graph or not select_concept(current_graph, state.evidence, concept["id"]):
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
        if not grounding_valid(reviewed_item, current_chunks, reviewed_receipt):
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
                **public_prompt(output),
                "sources": references,
                "authoredBy": "expert",
                "action": selected["action"],
                "objective": selected["objective"],
                "rationale": choice.rationale,
            },
            private={
                **({"correctChoiceId": output.correctChoiceId} if isinstance(output, Question) else {}),
                "explanation": output.explanation,
                "hint": output.hint,
                "question": output.model_dump(),
                "releaseId": release_id,
                "grounding": reviewed_receipt,
                "expertOnDemand": on_demand and memory_target is None,
                "memoryTarget": memory_target,
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
            "A source-grounded question is ready for the learner.",
            "assign_activity",
            "completed",
            references=references,
            artifacts=[
                {
                    "id": activity.id,
                    "kind": "activity",
                    "label": "Practice question",
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
