"""Isolated Tutor experiments using published course content and real agents."""

import re
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select

from learnloop.agents.tutoring.prompts import CHAT_PROMPT
from learnloop.agents.tutoring.workbench import lesson_for
from learnloop.core.domain import (
    DIFFICULTIES,
    concept_state,
    effective_state,
    prerequisite_block,
    target_difficulty,
)
from learnloop.core.errors import ServiceError
from learnloop.core.planning import candidates
from learnloop.core.schemas import (
    ExpertPromptStages,
    StrictModel,
    SubmitAnswer,
    WorkbenchTutorReply,
)
from learnloop.persistence.database import (
    Activity,
    Course,
    Job,
    LearnerState,
    ResponseDetail,
    Run,
    StudySession,
    Submission,
    WorkbenchMemory,
    now,
    uid,
)
from learnloop.persistence.learner_memory import learner_memory, record_tutor_observation
from learnloop.persistence.plans import get_plan
from learnloop.persistence.releases import (
    adopt_workbench_materials,
    current_material_release,
    get_release,
)
from learnloop.persistence.repository import course_graph, learner, public_activity
from learnloop.runtime.events import new_run, run_status
from learnloop.runtime.handoffs import HandoffRequest, handoff_view
from learnloop.runtime.usage import MeteredServices, UsageRecorder, usage_summary
from learnloop.runtime.workflows import PromptConfiguredServices


class MemoryCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class TutorTemplate(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    agent: Literal["tutor"]
    name: str = Field(min_length=1, max_length=200)
    prompts: ExpertPromptStages
    enabledTools: list[str] = Field(default_factory=list, max_length=16)
    model: str = Field(min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    basePrompts: Literal["v1", "v2"] = "v2"


class ExpertTemplate(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    agent: Literal["expert"]
    name: str = Field(min_length=1, max_length=200)
    prompts: ExpertPromptStages
    enabledTools: list[str] = Field(default_factory=list, max_length=16)
    model: str = Field(min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    basePrompts: Literal["v1", "v2"] = "v2"
    organizationVariant: Literal["baseline", "rules", "procedural", "exemplar"] = "baseline"


class Start(StrictModel):
    request: str = Field(default="", max_length=2000)
    conceptId: str | None = Field(default=None, min_length=1, max_length=100)
    mode: Literal["auto", "lesson", "quiz", "pre_assessment"]
    promptTemplate: TutorTemplate | None = None
    expertPromptTemplate: ExpertTemplate | None = None
    continuation: bool = False
    nextRound: bool = False
    stepId: str | None = Field(default=None, max_length=100)


PRE_ASSESSMENT_ROUND_SIZE = 15
PRE_ASSESSMENT_REVIEW_SLOTS = 3


def pre_assessment_round(plan, answered, round_number):
    """Cover new concepts first, reserving later-round space for spaced checks."""
    seen = list(dict.fromkeys(answered))
    remaining = [concept_id for concept_id in plan if concept_id not in seen]
    seen = [concept_id for concept_id in seen if concept_id in plan]
    if not seen:
        return remaining[:PRE_ASSESSMENT_ROUND_SIZE]
    review_count = min(PRE_ASSESSMENT_REVIEW_SLOTS, len(seen), PRE_ASSESSMENT_ROUND_SIZE - 1) if remaining else min(PRE_ASSESSMENT_ROUND_SIZE, len(seen))
    offset = ((round_number - 2) * PRE_ASSESSMENT_REVIEW_SLOTS) % len(seen)
    review = (seen[offset:] + seen[:offset])[:review_count]
    return remaining[:PRE_ASSESSMENT_ROUND_SIZE - review_count] + review


class ClearSession(StrictModel):
    sessionId: str = Field(min_length=1, max_length=100)
    stepId: str | None = Field(default=None, max_length=100)


class NotSure(StrictModel):
    operationId: str = Field(min_length=1, max_length=100)
    activityId: str = Field(min_length=1, max_length=100)
    expectedLearnerVersion: int = Field(ge=0)


class Chat(StrictModel):
    sessionId: str = Field(min_length=1, max_length=100)
    stepId: str | None = Field(default=None, max_length=100)
    operationId: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


def test_owner(memory):
    return "workbench:" + memory.id


def pick_concept(request, concepts):
    if len(concepts) == 1:
        return concepts[0]
    words = set(re.findall(r"[a-z0-9]+", request.lower())) - {
        "help", "learn", "understand", "lesson", "quiz", "question", "practice", "about", "please", "the", "me", "with", "test", "my", "on", "a", "i", "want",
    }
    scored = [(len(words & set(re.findall(r"[a-z0-9]+", c["title"].lower()))), c) for c in concepts]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored or not scored[0][0] or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        raise HTTPException(422, "Mention a specific course topic in the learning request.")
    return scored[0][1]


def build_router(context):
    router = APIRouter(tags=["Tutor workbench"])
    factory, owner, owned = context.factory, context.owner, context.owned

    def memory_for(db, memory_id, principal):
        memory = db.get(WorkbenchMemory, memory_id)
        if not memory or memory.owner_id != principal:
            raise HTTPException(404, "Memory session not found.")
        owned(db, Course, memory.course_id, principal)
        return memory

    def view(db, memory):
        state = learner(db, memory.course_id, test_owner(memory))
        session = db.get(StudySession, memory.session_id) if memory.session_id else None
        activity = db.get(Activity, session.current_activity_id) if session and session.current_activity_id else None
        submission = db.scalar(select(Submission).where(Submission.activity_id == activity.id)) if activity else None
        baseline = []
        if session and (memory.data.get("mode") == "pre_assessment" or memory.data.get("preAssessmentPlan")):
            baseline = list(db.execute(select(Submission, Activity).join(Activity, Submission.activity_id == Activity.id).where(
                Activity.session_id == session.id, Submission.owner_id == test_owner(memory)
            ).order_by(Submission.created_at, Submission.id)))
            baseline = [(s, a) for s, a in baseline if s.assessment and a.private.get("preAssessment")]
        round_start = memory.data.get("preAssessmentRoundStart", 0)
        round_results = baseline[round_start:]
        round_plan = memory.data.get("preAssessmentRoundPlan", memory.data.get("preAssessmentPlan", []))
        remaining = len(set(memory.data.get("preAssessmentPlan", [])) - {a.concept_id for _, a in baseline})
        runs = [db.get(Run, rid) for rid in memory.data.get("runIds", [])]
        # Keep the active learning session pinned to its original publication,
        # while the brain map always represents the latest course publication.
        # This lets newly published materials appear without changing the
        # content already being used by an in-progress lesson or quiz.
        release = get_release(db, memory.course_id, session.release_id if session else None)
        latest_release = current_material_release(db, memory.course_id) or get_release(
            db, memory.course_id
        )
        graph = course_graph(db, memory.course_id, release.id) if release else {"concepts": []}
        latest_graph = course_graph(db, memory.course_id, latest_release.id) if latest_release else {"concepts": []}
        history = db.execute(
            select(Submission, Activity)
            .join(Activity, Submission.activity_id == Activity.id)
            .join(StudySession, Activity.session_id == StudySession.id)
            .where(StudySession.course_id == memory.course_id, Submission.owner_id == test_owner(memory))
            .order_by(Submission.created_at.desc())
            .limit(50)
        )
        session_count = db.scalar(select(func.count(StudySession.id)).where(
            StudySession.course_id == memory.course_id, StudySession.owner_id == test_owner(memory)
        ))
        load_run = next((r for r in runs if r and r.snapshot.get("workflow") == "next_activity"), None)
        load_duration = memory.data.get("loadDurationMs")
        load_usage = usage_summary(memory.data.get("loadUsage"))
        if load_run:
            started = load_run.input.get("_started_at")
            end = None if load_run.snapshot.get("status") in ("queued", "running") else next((
                e.get("at") for e in reversed(load_run.snapshot.get("events", []))
                if e.get("type") == "run.status" and e.get("payload", {}).get("status") in
                ("waiting_for_learner", "completed", "failed", "needs_review", "paused")
            ), None)
            if started:
                end_time = datetime.fromisoformat(end) if end else now()
                load_duration = max(0, int((end_time - datetime.fromisoformat(started)).total_seconds() * 1000))
            load_usage = usage_summary(load_run.input.get("_usage_calls"))
        def public_graph(source):
            return {
                "concepts": [{"id": c["id"], "title": c["title"], "targetDifficulty": target_difficulty(c)} for c in source["concepts"]],
                "topics": [{"id": t["id"], "title": t["title"], "summary": t.get("summary", ""), "parentId": t.get("parentId"), "conceptIds": t["conceptIds"]} for t in source.get("topics", [])],
                "prerequisites": [{"prerequisite": e["prerequisite"], "dependent": e["dependent"]} for e in source.get("prerequisites", [])],
                "related": [{"first": e["first"], "second": e["second"]} for e in source.get("related", [])],
            }

        return {
            "id": memory.id, "name": memory.name, "courseId": memory.course_id,
            "sessionId": memory.session_id,
            "stepId": memory.data.get("stepId"),
            "version": state.version, "evidence": state.evidence,
            # Use the same release as the active session, and the same effective
            # evidence policy as the learner's memory (including review dates).
            "graph": public_graph(graph),
            "courseGraph": public_graph(latest_graph),
            "evidenceStates": {
                c["id"]: {level: effective_state(state.evidence.get(c["id"], {}).get(level)) for level in DIFFICULTIES}
                for c in graph["concepts"]
            },
            "courseEvidenceStates": {
                c["id"]: {level: effective_state(state.evidence.get(c["id"], {}).get(level)) for level in DIFFICULTIES}
                for c in latest_graph["concepts"]
            },
            "memory": learner_memory(db, state, release.id, graph["concepts"]) if release else {},
            "courseMemory": learner_memory(db, state, latest_release.id, latest_graph["concepts"]) if latest_release else {},
            "request": memory.data.get("request", ""), "mode": memory.data.get("mode", "auto"),
            "branch": memory.data.get("branch"), "lesson": memory.data.get("lesson"),
            "preAssessment": {"total": len(round_plan) or 3, "completed": len(round_results), "round": memory.data.get("preAssessmentRound", 1), "remaining": remaining, "results": [
                {"conceptId": a.concept_id, "correct": s.assessment.get("correct"), "uncertain": s.assessment.get("uncertain"), "demonstrated": s.assessment.get("evidenceOutcome") == "demonstration", "feedback": s.assessment.get("feedback", "")} for s, a in round_results
            ]} if memory.data.get("mode") == "pre_assessment" else None,
            "preAssessmentResume": bool(memory.data.get("mode") != "pre_assessment" and round_plan and len(round_results) == len(round_plan)),
            "chat": memory.data.get("chat", []),
            "activity": public_activity(activity),
            "assessment": submission.assessment if submission and submission.assessment else None,
            "selectedChoiceId": submission.choice_id if submission else None,
            "answer": (db.get(ResponseDetail, submission.id).answer if submission and db.get(ResponseDetail, submission.id) else None),
            "history": [{"id": s.id, "conceptId": a.concept_id, "difficulty": a.difficulty, "assessment": s.assessment, "preAssessment": bool(a.private.get("preAssessment"))} for s, a in history if s.assessment],
            "runs": [r.snapshot for r in runs if r],
            "handoffs": [item for r in runs if r for item in ([{
                "request": r.input["_expert_question_handoff"]["request"], "runId": r.id,
                "status": r.input["_expert_question_handoff"]["status"],
                "summary": r.input["_expert_question_handoff"].get("summary", "Preparing a source-grounded question."),
                "result": {"sourceCount": len(r.input["_expert_question_handoff"]["result"]["passageIds"])} if r.input["_expert_question_handoff"].get("result") else None,
                "retryable": bool(set(r.snapshot.get("allowedCommands", [])) & {"retry", "resume"}),
            }] if r.input.get("_expert_question_handoff") else []) + ([{
                "request": r.input["_expert_lesson_handoff"]["request"], "runId": r.id,
                "status": r.input["_expert_lesson_handoff"]["status"],
                "summary": r.input["_expert_lesson_handoff"].get("summary", "Preparing a source-grounded lesson."),
                "result": {"sourceCount": len(r.input["_expert_lesson_handoff"]["result"]["passageIds"])} if r.input["_expert_lesson_handoff"].get("result") else None,
                "retryable": bool(set(r.snapshot.get("allowedCommands", [])) & {"retry", "resume"}),
            }] if r.input.get("_expert_lesson_handoff") else []) + ([handoff_view(r, db.get(Submission, r.input.get("submission_id")))] if r.input.get("handoff") else [])],
            "statistics": {"sessions": session_count, "loadDurationMs": load_duration, "loadUsage": load_usage},
        }

    @router.get("/api/workbench/courses/{course_id}/memories")
    def memories(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            return [{"id": m.id, "name": m.name} for m in db.scalars(
                select(WorkbenchMemory).where(WorkbenchMemory.course_id == course_id, WorkbenchMemory.owner_id == principal).order_by(WorkbenchMemory.created_at)
            )]

    @router.post("/api/workbench/courses/{course_id}/memories", status_code=201)
    def create_memory(course_id: str, body: MemoryCreate, principal=Depends(owner)):
        with factory.begin() as db:
            owned(db, Course, course_id, principal)
            memory = WorkbenchMemory(course_id=course_id, owner_id=principal, name=body.name, data={})
            db.add(memory)
            db.flush()
            db.add(LearnerState(course_id=course_id, owner_id=test_owner(memory), version=0, evidence={}))
            return {"id": memory.id, "name": memory.name}

    @router.get("/api/workbench/memories/{memory_id}")
    def get_memory(memory_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            return view(db, memory_for(db, memory_id, principal))

    @router.post("/api/workbench/memories/{memory_id}/clear")
    def clear_session(memory_id: str, body: ClearSession, principal=Depends(owner)):
        with factory.begin() as db:
            memory = memory_for(db, memory_id, principal)
            db.scalar(select(Course).where(Course.id == memory.course_id).with_for_update())
            db.refresh(memory, with_for_update=True)
            if memory.session_id != body.sessionId or memory.data.get("stepId") != body.stepId:
                raise HTTPException(409, "The session changed. Refresh before clearing it.")
            session = db.get(StudySession, memory.session_id)
            if not session or session.owner_id != test_owner(memory):
                raise HTTPException(409, "The saved session is unavailable.")
            activity = db.get(Activity, session.current_activity_id) if session.current_activity_id else None
            runs = [db.get(Run, rid) for rid in memory.data.get("runIds", [])]
            if activity and activity.status == "submitted":
                raise HTTPException(409, "Wait for assessment to finish before clearing this session.")
            if any(run and run.snapshot["status"] in ("queued", "running", "paused") for run in runs):
                raise HTTPException(409, "Wait for the current run to finish before clearing this session.")
            if activity and activity.status == "pending":
                activity.status = "skipped"
            session.status = "ended"
            memory.session_id = None
            memory.data = {}
            return view(db, memory)

    @router.post("/api/workbench/memories/{memory_id}/start", status_code=202)
    def start(memory_id: str, body: Start, principal=Depends(owner)):
        started_at = time.perf_counter()
        with factory.begin() as db:
            if body.nextRound and (not body.continuation or body.mode != "pre_assessment"):
                raise HTTPException(422, "Start the next round from a completed pre-assessment.")
            memory = memory_for(db, memory_id, principal)
            course = db.scalar(select(Course).where(Course.id == memory.course_id).with_for_update())
            previous = db.get(StudySession, memory.session_id) if memory.session_id else None
            if body.continuation and memory.data.get("stepId") != body.stepId:
                raise HTTPException(409, "The learning step changed. Refresh before continuing.")
            if previous:
                current = db.get(Activity, previous.current_activity_id) if previous.current_activity_id else None
                old_runs = [db.get(Run, rid) for rid in memory.data.get("runIds", [])]
                if current and current.status in ("pending", "submitted"):
                    raise HTTPException(409, "Finish the current question before starting another run.")
                if any(r and r.snapshot["status"] in ("queued", "running", "paused") for r in old_runs):
                    raise HTTPException(409, "The current run is still active. Resume or retry it first.")
                if not body.continuation:
                    previous.status = "ended"
            if body.continuation and not previous:
                raise HTTPException(409, "There is no active session to continue.")
            if body.continuation and body.mode == "pre_assessment":
                if not body.nextRound and (memory.data.get("mode") != "pre_assessment" or not current or not current.private.get("preAssessment")):
                    raise HTTPException(409, "Start a pre-assessment before continuing it.")
                if not memory.data.get("preAssessmentPlan"):
                    raise HTTPException(409, "This pre-assessment uses the previous format. Clear the session and start a new pre-assessment to cover the course.")
                answered = [(s, a) for s, a in db.execute(select(Submission, Activity).join(Activity, Submission.activity_id == Activity.id).where(
                    Activity.session_id == previous.id, Submission.owner_id == test_owner(memory)
                ).order_by(Submission.created_at, Submission.id)) if s.assessment and a.private.get("preAssessment")]
                completed = len(answered) - memory.data.get("preAssessmentRoundStart", 0)
                current_plan = memory.data.get("preAssessmentRoundPlan", memory.data["preAssessmentPlan"])
                if not completed or (body.nextRound and completed != len(current_plan)) or (not body.nextRound and completed >= len(current_plan)):
                    raise HTTPException(409, "Finish this round before starting the next one." if body.nextRound else "This round is complete. Start the next round to continue.")
            if body.continuation:
                release = get_release(db, course.id, previous.release_id if previous else None)
            else:
                try:
                    release = adopt_workbench_materials(db, course.id)
                except (ServiceError, ValueError) as exc:
                    raise HTTPException(409, getattr(exc, "message", str(exc))) from exc
            if not release:
                raise HTTPException(409, "Prepare course materials in Workbench before starting a Tutor run.")
            graph = course_graph(db, course.id, release.id)
            pre_plan = memory.data.get("preAssessmentPlan", []) if body.continuation else []
            round_number = memory.data.get("preAssessmentRound", 1) if body.continuation else 1
            round_start = memory.data.get("preAssessmentRoundStart", 0) if body.continuation else 0
            round_plan = memory.data.get("preAssessmentRoundPlan", pre_plan) if body.continuation else []
            if body.mode == "pre_assessment" and not body.continuation:
                pre_plan = [c["id"] for c in graph["concepts"]]
                if not pre_plan:
                    raise HTTPException(409, "Publish course concepts before starting a pre-assessment.")
                round_plan = pre_assessment_round(pre_plan, [], 1)
            elif body.mode == "pre_assessment" and body.nextRound:
                round_number += 1
                round_start = len(answered)
                round_plan = pre_assessment_round(pre_plan, [a.concept_id for _, a in answered], round_number)
                completed = 0
                if not round_plan:
                    raise HTTPException(409, "No concepts are available for another round.")
            branch = "quiz" if body.mode == "pre_assessment" else body.mode
            state = learner(db, course.id, test_owner(memory), lock=True)
            continuing_id = memory.data.get("conceptId") if body.continuation and previous else None
            conversation = [{"role": turn["role"], "text": turn["text"], **({"nextAction": turn["nextAction"]} if turn.get("nextAction") else {})} for turn in memory.data.get("chat", [])[-12:]] if body.continuation else []
            previous_activity = None
            if body.continuation and previous:
                submitted = db.scalar(select(Submission).where(Submission.activity_id == current.id)) if current else None
                previous_activity = {"kind": memory.data.get("branch"), "conceptId": continuing_id, "assessment": submitted.assessment if submitted and submitted.assessment else None}
            if body.mode == "pre_assessment":
                concept_id = round_plan[completed if body.continuation else 0]
                concept = next((c for c in graph["concepts"] if c["id"] == concept_id), None)
                if not concept:
                    raise HTTPException(409, "A pre-assessment concept is no longer published.")
            elif continuing_id:
                concept = next((c for c in graph["concepts"] if c["id"] == continuing_id), None)
                if not concept:
                    raise HTTPException(409, "The previous topic is no longer published.")
                if memory.data.get("mode") == "pre_assessment" and body.mode == "lesson":
                    concept = next((c for c in graph["concepts"] if c["id"] in pre_plan and concept_state(c, state.evidence) != "demonstrated"), concept)
                # A lesson does not satisfy prerequisite evidence. Continue at an
                # eligible prerequisite instead of repeatedly showing a blocked lesson.
                if previous_activity and previous_activity["kind"] == "lesson":
                    blocked = prerequisite_block(graph, state.evidence, concept["id"])
                    next_id = (blocked or {}).get("nextStep", {}).get("conceptId")
                    if next_id:
                        concept = next((c for c in graph["concepts"] if c["id"] == next_id), concept)
                # Continue practice on the same concept until its target level is
                # demonstrated. Afterwards, choose among eligible next concepts.
                if previous_activity and previous_activity["assessment"] and memory.data.get("mode") != "pre_assessment" and concept_state(concept, state.evidence) == "demonstrated":
                    plan = get_plan(db, course.id, state.owner_id)
                    memory_context = learner_memory(db, state, release.id, graph["concepts"])
                    options = candidates(
                        graph, state.evidence, plan.goal if plan else None,
                        previous=continuing_id,
                        review_dates=plan.data.get("reviewDates") if plan else None,
                        memory=memory_context,
                    )
                    if not options:
                        raise HTTPException(409, "No eligible topic needs practice right now. Review the course map or return when review is due.")
                    concept = next(c for c in graph["concepts"] if c["id"] == options[0]["conceptId"])
            elif body.conceptId:
                concept = next((c for c in graph["concepts"] if c["id"] == body.conceptId), None)
                if not concept:
                    raise HTTPException(422, "The selected concept is not in the published course.")
            elif body.request:
                concept = pick_concept(body.request, graph["concepts"])
            else:
                plan = get_plan(db, course.id, state.owner_id)
                memory_context = learner_memory(db, state, release.id, graph["concepts"])
                options = candidates(
                    graph, state.evidence, plan.goal if plan else None,
                    previous=current.concept_id if previous and current else None,
                    review_dates=plan.data.get("reviewDates") if plan else None,
                    memory=memory_context,
                )
                concept_id = options[0]["conceptId"] if options else None
                if not concept_id and branch in ("lesson", "auto") and graph["concepts"]:
                    concept_id = graph["concepts"][0]["id"]
                concept = next((c for c in graph["concepts"] if c["id"] == concept_id), None)
                if not concept:
                    raise HTTPException(409, "No eligible topic is available. Review the course or try a lesson.")
            if branch == "quiz" and body.mode != "pre_assessment":
                if blocked := prerequisite_block(graph, state.evidence, concept["id"]):
                    raise HTTPException(409, blocked)
            chat_history = memory.data.get("chat", []) if body.continuation else []
            chat_usage = memory.data.get("chatUsage", []) if body.continuation else []
            if body.continuation:
                session = previous
                session.current_activity_id = None
            else:
                session = StudySession(course_id=course.id, owner_id=test_owner(memory), release_id=release.id)
                db.add(session)
                db.flush()
            memory.session_id = session.id
            expert_template = body.expertPromptTemplate.model_dump() if body.expertPromptTemplate else None
            if expert_template is None and body.continuation:
                expert_template = memory.data.get("expertPromptTemplate")
            memory.data = {"request": body.request, "mode": body.mode, "branch": branch, "conceptId": concept["id"], "stepId": uid(), "runIds": [], "chat": chat_history, "chatUsage": chat_usage, "promptTemplate": body.promptTemplate.model_dump() if body.promptTemplate else None, "expertPromptTemplate": expert_template, **({"preAssessmentPlan": pre_plan, "preAssessmentRoundPlan": round_plan, "preAssessmentRound": round_number, "preAssessmentRoundStart": round_start} if pre_plan and (body.mode == "pre_assessment" or body.continuation) else {})}
            if branch == "lesson":
                material = lesson_for(db, course.id, release.id, concept["id"])
                if material:
                    memory.data = {**memory.data, "lesson": material, "loadUsage": [], "loadDurationMs": int((time.perf_counter() - started_at) * 1000)}
            if branch != "lesson" or not material:
                run = new_run(db, course, "next_activity", {
                    "session_id": session.id, "target_concept_id": concept["id"],
                    "mixed_question_formats": True,
                    "workbench_pre_assessment": body.mode == "pre_assessment",
                    "learning_request": body.request,
                    "conversation": conversation,
                    "previous_activity": previous_activity,
                    "workbench_auto": branch in ("auto", "lesson"),
                    "workbench_force_lesson": branch == "lesson",
                    "prompt_template": body.promptTemplate.model_dump() if body.promptTemplate else None,
                    "expert_prompt_template": expert_template,
                    "workbench_memory_id": memory.id,
                    "workbench_step_id": memory.data["stepId"],
                }, concept["id"])
                run.owner_id = test_owner(memory)
                memory.data = {**memory.data, "runIds": [run.id]}
            return view(db, memory)

    @router.post("/api/workbench/memories/{memory_id}/not-sure")
    def not_sure(memory_id: str, body: NotSure, principal=Depends(owner)):
        with factory.begin() as db:
            memory = memory_for(db, memory_id, principal)
            db.scalar(select(Course).where(Course.id == memory.course_id).with_for_update())
            session = db.get(StudySession, memory.session_id) if memory.session_id else None
            activity = db.get(Activity, session.current_activity_id) if session and session.current_activity_id else None
            if memory.data.get("mode") != "pre_assessment" or not activity or activity.id != body.activityId:
                raise HTTPException(409, "The pre-assessment question changed. Refresh before continuing.")
            existing = db.scalar(select(Submission).where(Submission.owner_id == test_owner(memory), Submission.operation_id == body.operationId))
            if existing:
                if existing.activity_id != activity.id or existing.expected_version != body.expectedLearnerVersion or not existing.assessment.get("notSure"):
                    raise HTTPException(409, "Operation ID already belongs to a different answer.")
                return view(db, memory)
            state = learner(db, memory.course_id, test_owner(memory), lock=True)
            if activity.status != "pending" or state.version != body.expectedLearnerVersion:
                raise HTTPException(409, "Question or memory changed. Refresh before continuing.")
            submission = Submission(activity_id=activity.id, owner_id=test_owner(memory), operation_id=body.operationId, expected_version=state.version, choice_id="")
            db.add(submission)
            db.flush()
            state.version += 1
            submission.assessment = {
                "correct": False, "uncertain": True, "notSure": True, "hinted": activity.hinted,
                "feedback": "You marked this question as not sure. This concept is available to review.",
                "explanation": activity.private.get("explanation", ""),
                "difficulty": activity.difficulty, "learnerVersion": state.version,
                "assessmentId": submission.id, "evidenceOutcome": "not_sure",
            }
            activity.private = {**activity.private, "preAssessment": True}
            activity.status = "assessed"
            return view(db, memory)

    @router.post("/api/workbench/memories/{memory_id}/answer", status_code=202)
    def answer(memory_id: str, body: SubmitAnswer, principal=Depends(owner)):
        with factory.begin() as db:
            memory = memory_for(db, memory_id, principal)
            course = db.scalar(select(Course).where(Course.id == memory.course_id).with_for_update())
            session = db.get(StudySession, memory.session_id) if memory.session_id else None
            activity = db.get(Activity, session.current_activity_id) if session and session.current_activity_id else None
            if not activity:
                raise HTTPException(409, "There is no question to answer.")
            question_format = activity.public.get("format", "single_answer")
            available = {c["id"] for c in activity.public["choices"]}
            typed_answer = body.typed_answer()
            valid = (body.choiceId in available if question_format == "single_answer" else
                     body.choiceIds is not None and set(body.choiceIds) <= available if question_format == "multiple_answer" else
                     body.blanks is not None and {b.id for b in body.blanks} == set(activity.public["blankIds"]) if question_format == "fill_in" else
                     question_format == "open" and body.answerText is not None)
            if not valid or body.reasoning:
                raise HTTPException(422, "Submit an answer that matches this question's format.")
            existing = db.scalar(select(Submission).where(Submission.owner_id == test_owner(memory), Submission.operation_id == body.operationId))
            if existing:
                detail = db.get(ResponseDetail, existing.id)
                if existing.activity_id != activity.id or existing.choice_id != (body.choiceId or "") or existing.expected_version != body.expectedLearnerVersion or (detail.answer if detail else None) != typed_answer:
                    raise HTTPException(409, "Operation ID already belongs to a different answer.")
                return view(db, memory)
            state = learner(db, course.id, test_owner(memory), lock=True)
            if activity.status != "pending" or state.version != body.expectedLearnerVersion:
                raise HTTPException(409, "Question or memory changed. Refresh before submitting.")
            submission = Submission(activity_id=activity.id, owner_id=test_owner(memory), operation_id=body.operationId, expected_version=state.version, choice_id=body.choiceId or "")
            db.add(submission)
            db.flush()
            start_time = activity.private.get("presentedAt") or activity.private.get("assignedAt")
            submitted = now()
            elapsed = max(0, int((submitted - datetime.fromisoformat(start_time)).total_seconds() * 1000)) if start_time else None
            db.add(ResponseDetail(submission_id=submission.id, reasoning=None, answer=typed_answer, timing={"startedAt": start_time, "submittedAt": submitted.isoformat(), "responseTimeMs": elapsed, "basis": "assignment" if start_time else "unavailable"}))
            activity.status = "submitted"
            if memory.data.get("mode") == "pre_assessment":
                activity.private = {**activity.private, "preAssessment": True}
            parent = next((r for r in reversed([db.get(Run, rid) for rid in memory.data.get("runIds", [])]) if r and r.snapshot.get("workflow") == "next_activity"), None)
            handoff = HandoffRequest(
                requestId=body.operationId, parentRunId=parent.id if parent else None,
                sessionId=session.id, stepId=memory.data.get("stepId"), courseReleaseId=session.release_id,
                conceptId=activity.concept_id, difficulty=activity.difficulty, targetAgent="assessing",
                task="assess_answer", input={"submissionId": submission.id},
            )
            run = new_run(db, course, "assessment", {"session_id": session.id, "submission_id": submission.id, "workbench_memory_id": memory.id, "handoff": handoff.model_dump()}, activity.concept_id)
            run.owner_id = test_owner(memory)
            memory.data = {**memory.data, "runIds": [*memory.data.get("runIds", []), run.id]}
            return view(db, memory)

    @router.post("/api/workbench/memories/{memory_id}/chat")
    def chat(memory_id: str, body: Chat, principal=Depends(owner)):
        with factory.begin() as db:
            memory = memory_for(db, memory_id, principal)
            session = db.get(StudySession, memory.session_id) if memory.session_id else None
            if not session or session.id != body.sessionId or session.status != "active" or memory.data.get("stepId") != body.stepId:
                raise HTTPException(409, "The session changed. Refresh before messaging the Tutor.")
            prior = memory.data.get("chat", [])
            existing = next((turn for turn in prior if turn.get("operationId") == body.operationId), None)
            if existing and existing["text"] != body.message:
                raise HTTPException(409, "Operation ID already belongs to a different message.")
            if existing:
                return view(db, memory)
            activity = db.get(Activity, session.current_activity_id) if session.current_activity_id else None
            if activity and activity.status == "submitted":
                raise HTTPException(409, "Wait for your answer to be assessed before chatting.")
            if any(r and r.snapshot["status"] in ("queued", "running", "paused") for r in (db.get(Run, rid) for rid in memory.data.get("runIds", []))):
                raise HTTPException(409, "Wait for the current activity to finish loading.")
            concept_id = activity.concept_id if activity else memory.data.get("conceptId")
            concept = next((c for c in course_graph(db, session.course_id, session.release_id)["concepts"] if c["id"] == concept_id), None)
            material = lesson_for(db, session.course_id, session.release_id, concept_id) if concept else None
            if not concept or not material:
                raise HTTPException(409, "The current lesson is not available for tutoring.")
            state = learner(db, session.course_id, session.owner_id)
            level = activity.difficulty if activity else None
            context_data = {
                "concept": concept, "lesson": material.get("lessonsByDifficulty", {}).get(level, material["lesson"]),
                "activity": public_activity(activity), "assessment_pending": bool(activity and activity.status == "pending"),
                "history": [{"role": turn["role"], "text": turn["text"]} for turn in prior[-12:]],
                "message": body.message,
                "learnerMemory": learner_memory(db, state, session.release_id, [concept])[concept_id],
            }
            course_id, session_id = session.course_id, session.id
            activity_id, activity_status = (activity.id, activity.status) if activity else (None, None)
            history_snapshot = list(prior)
            sources = material.get("sourcesByDifficulty", {}).get(level, material["sources"])
            from learnloop.runtime.events import default_template
            template = memory.data.get("promptTemplate") or default_template(db, principal, "tutor")
        recorder = UsageRecorder()
        chat_services = PromptConfiguredServices(MeteredServices(context.services, recorder), template)
        response = chat_services.generate(
            "Tutoring", CHAT_PROMPT + "\nAlso choose nextAction: lesson, quiz, or none. "
            "Suggest a lesson when more explanation is needed and a quiz when practice is appropriate. "
            "The current unanswered quiz stays visible until answered or cleared.",
            context_data, WorkbenchTutorReply,
        )
        with factory.begin() as db:
            db.scalar(select(Course).where(Course.id == course_id).with_for_update())
            memory = memory_for(db, memory_id, principal)
            session = db.get(StudySession, session_id)
            activity = db.get(Activity, activity_id) if activity_id else None
            if memory.session_id != session_id or memory.data.get("stepId") != body.stepId or not session or session.status != "active" or session.current_activity_id != activity_id or (activity and activity.status != activity_status):
                raise HTTPException(409, "The learning step changed while the Tutor replied. Refresh and try again.")
            existing = next((turn for turn in memory.data.get("chat", []) if turn.get("operationId") == body.operationId), None)
            if existing and existing["text"] != body.message:
                raise HTTPException(409, "Operation ID already belongs to a different message.")
            if existing:
                return view(db, memory)
            if memory.data.get("chat", []) != history_snapshot:
                raise HTTPException(409, "The conversation changed. Refresh and try again.")
            if activity and activity.status == "pending":
                activity.hinted = True
            if activity:
                record_tutor_observation(activity, body.message, response.observation)
            turns = [*memory.data.get("chat", []),
                     {"role": "user", "text": body.message, "operationId": body.operationId},
                     {"role": "assistant", "text": response.text, "nextAction": response.nextAction, "sources": sources}]
            memory.data = {**memory.data, "chat": turns[-40:], "chatUsage": [*memory.data.get("chatUsage", []), *recorder.calls()]}
            return view(db, memory)

    @router.post("/api/workbench/memories/{memory_id}/retry")
    def retry(memory_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            memory = memory_for(db, memory_id, principal)
            ids = memory.data.get("runIds", [])
            run = db.get(Run, ids[-1]) if ids else None
            job = db.scalar(select(Job).where(Job.run_id == run.id).with_for_update()) if run else None
            if not run or not job or not set(run.snapshot.get("allowedCommands", [])) & {"retry", "resume"} or job.attempts >= context.settings.worker_max_attempts:
                raise HTTPException(409, "This run cannot be retried. Start a new run if possible.")
            job.status, job.lease_until = "queued", None
            run_status(db, run.id, "queued", "Waiting for the worker to continue.")
            return view(db, memory)

    return router
