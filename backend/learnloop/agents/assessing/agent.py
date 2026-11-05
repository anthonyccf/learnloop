"""Assessing Agent entry point: review an answer and commit validated evidence.

Correctness comes from the server-held key; the model provides feedback and
uncertainty. domain.assess_evidence determines transitions, and the assessment,
learner version and accepted event commit together. This never advances a lesson.
"""

import copy

from sqlalchemy import select

from learnloop.agents.assessing.prompts import FEEDBACK_PROMPT
from learnloop.agents.question_review import question_review_valid, review_question
from learnloop.agents.rubrics import ensure_rubric, validate_assessment
from learnloop.core.domain import WEAKNESS_FAILURE_THRESHOLD, assess_evidence, effective_state
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import source_ids
from learnloop.core.schemas import Assessment, Question
from learnloop.persistence.database import (
    Activity,
    Chunk,
    Course,
    Document,
    ResponseDetail,
    Run,
    StudySession,
    Submission,
    now,
)
from learnloop.persistence.releases import pin_session
from learnloop.persistence.repository import grounding_chunks, learner
from learnloop.runtime.events import accept, pending, run_status, step


def run(factory, services, run_id):
    with factory.begin() as db:
        run = db.get(Run, run_id)
        submission = db.get(Submission, run.input["submission_id"])
        activity = db.get(Activity, submission.activity_id)
        session = db.get(StudySession, activity.session_id)
        release_id = pin_session(db, session)
        run.input = {**run.input, "release_id": release_id}
        # Resume after a committed assessment without committing it twice.
        already_assessed = bool(submission.assessment)
        if not already_assessed:
            run_status(db, run_id, "running", "Assessing the submitted response.")
            step(
                db,
                run_id,
                "assessing",
                "Check response evidence",
                "Evaluate the response and persisted hint usage against the server-held answer key.",
                "assess_response",
            )
        correct = submission.choice_id == activity.private["correctChoiceId"]
        state = learner(db, session.course_id, session.owner_id)
        evidence_version = state.version
        prior = copy.deepcopy(
            state.evidence.get(activity.concept_id, {}).get(activity.difficulty, {})
        )
        detail = db.get(ResponseDetail, submission.id)
        reasoning = detail.reasoning if detail else None
        timing = detail.timing if detail else {"responseTimeMs": None, "basis": "unavailable"}
        history = list(
            db.scalars(
                select(Submission)
                .join(Activity, Submission.activity_id == Activity.id)
                .join(StudySession, Activity.session_id == StudySession.id)
                .where(
                    StudySession.course_id == session.course_id,
                    Submission.owner_id == session.owner_id,
                    Activity.concept_id == activity.concept_id,
                    Activity.difficulty == activity.difficulty,
                    Submission.id != submission.id,
                )
                .order_by(Submission.created_at.desc())
                .limit(8)
            )
        )
        context = {
            "question": activity.public,
            "selectedChoiceId": submission.choice_id,
            "correct": correct,
            "hintUsed": activity.hinted,
            "answerExplanation": activity.private["explanation"],
            "reasoning": reasoning,
            "timing": timing,
            "priorEvidence": prior,
            "previousAssessments": [
                {"assessmentId": s.id, "at": s.created_at.isoformat(), "assessment": s.assessment}
                for s in history
                if s.assessment
            ],
        }
        submission_id, course_id, owner_id = (
            submission.id,
            session.course_id,
            session.owner_id,
        )
        if not already_assessed:
            saved_question = activity.private.get("question")
            if saved_question:
                sources = saved_question["sources"]
                passages = grounding_chunks(
                    db, course_id, owner_id, source_ids(saved_question), release_id
                )
            else:
                # Legacy activities retain only public page anchors. Resolve every
                # anchor in this course, then review the actual question and key.
                passages = {}
                anchors = activity.public.get("sources", [])
                if not anchors:
                    raise ServiceError(
                        "no_grounding",
                        "This activity has no source evidence. Review it before assessment.",
                        False,
                    )
                for ref in anchors:
                    ids = list(
                        db.scalars(
                            select(Chunk.id)
                            .join(Document, Chunk.document_id == Document.id)
                            .where(
                                Document.course_id == course_id,
                                Document.id == ref["documentId"],
                                Chunk.page == ref["page"],
                            )
                        )
                    )
                    resolved = grounding_chunks(db, course_id, owner_id, ids, release_id)
                    if not resolved:
                        raise ServiceError(
                            "invalid_source",
                            "An activity source is no longer available. Review it before assessment.",
                            False,
                        )
                    passages.update(resolved)
                sources = [{"chunkId": id, "quote": c["text"][:600]} for id, c in passages.items()]
            question = {
                "prompt": activity.public["prompt"],
                "choices": activity.public["choices"],
                "correctChoiceId": activity.private["correctChoiceId"],
                "explanation": activity.private["explanation"],
                "hint": activity.private["hint"],
                "sources": sources,
            }
            receipt = activity.private.get("grounding")
            if saved_question and "difficulty" in saved_question:
                question["difficulty"] = activity.difficulty
            if saved_question and saved_question.get("rubric"):
                question["rubric"] = saved_question["rubric"]
                question["referenceAnswer"] = saved_question["referenceAnswer"]
    if not already_assessed:
        rubric_question = ensure_rubric(
            services, Question.model_validate(question), list(passages.values())
        )
        question = rubric_question.model_dump()
        reviewed_receipt = review_question(services, "Assessing", question, passages, receipt)
        context["extendedTopic"] = reviewed_receipt["status"] == "extended"
        context["passages"] = [{"chunkId": id, "text": c["text"]} for id, c in passages.items()]
        context["difficulty"] = activity.difficulty
        context["rubric"] = [c.model_dump() for c in rubric_question.rubric]
        context["referenceAnswer"] = rubric_question.referenceAnswer
        output = services.generate(
            "Assessing",
            FEEDBACK_PROMPT,
            context,
            Assessment,
        )
        coverage, score = validate_assessment(
            rubric_question, output, submission.choice_id, reasoning
        )
        rubric_met = score >= 1.0
        partial = 0 < score < 1.0
        contradiction = bool(
            output.contradiction
            or (
                effective_state(prior) in ("demonstrated", "review_due")
                and (not correct or not rubric_met or output.uncertain)
            )
        )
        uncertain = output.uncertain or (output.contradiction and correct and rubric_met)
        with factory.begin() as db:
            db.scalar(select(Course).where(Course.id == course_id).with_for_update())
            state = learner(db, course_id, owner_id, lock=True)
            submission = db.get(Submission, submission_id)
            activity = db.get(Activity, submission.activity_id)
            if not submission.assessment:
                if state.version != evidence_version:
                    raise ServiceError(
                        "learner_changed",
                        "Learner evidence changed during assessment. Retry to assess against current evidence.",
                    )
                current_chunks = grounding_chunks(
                    db, course_id, owner_id, source_ids(question), release_id
                )
                if not question_review_valid(question, current_chunks, reviewed_receipt):
                    raise ServiceError(
                        "source_changed",
                        "Course evidence changed during assessment. Review it before recording progress.",
                        False,
                    )
                evidence = copy.deepcopy(state.evidence)
                levels = evidence.setdefault(activity.concept_id, {})
                before, record = assess_evidence(
                    levels.get(activity.difficulty),
                    activity.id,
                    correct and rubric_met,
                    activity.hinted,
                    uncertain,
                    now(),
                )
                record["lastOutcome"]["partial"] = partial
                record["assessmentIds"] = [*prior.get("assessmentIds", []), submission.id]
                record["lastRubricScore"] = score
                record["responseTimeMs"] = timing.get("responseTimeMs")
                record["misconceptions"] = [
                    *prior.get("misconceptions", []),
                    *[
                        {**m.model_dump(), "assessmentId": submission.id}
                        for m in output.misconceptions
                    ],
                ]
                record["contradictions"] = [
                    *prior.get("contradictions", []),
                    *(
                        [
                            {
                                "assessmentId": submission.id,
                                "priorAssessmentIds": prior.get("assessmentIds", []),
                                "status": "needs_reassessment",
                            }
                        ]
                        if contradiction
                        else []
                    ),
                ]
                if record.get("confirmedWeakness", {}).get("status") == "active":
                    record["contradictions"] = [
                        {**item, "status": "confirmed_weakness", "confirmedBy": submission.id}
                        if item.get("status") == "needs_reassessment"
                        else item
                        for item in record["contradictions"]
                    ]
                    if (
                        record["lastTransition"]["outcome"] == "confirmed_weakness"
                        and not prior.get("confirmedWeakness", {}).get("status") == "active"
                    ):
                        confirmation_ids = [*prior.get("assessmentIds", []), submission.id]
                        record["confirmedWeakness"]["assessmentIds"] = confirmation_ids[
                            -WEAKNESS_FAILURE_THRESHOLD:
                        ]
                        record["weaknessHistory"][-1]["assessmentIds"] = confirmation_ids[
                            -WEAKNESS_FAILURE_THRESHOLD:
                        ]
                if record["state"] == "demonstrated":
                    record["contradictions"] = [
                        {**item, "status": "resolved", "resolvedBy": submission.id}
                        if item.get("status") != "resolved"
                        else item
                        for item in record["contradictions"]
                    ]
                candidate = {
                    "conceptId": activity.concept_id,
                    "difficulty": activity.difficulty,
                    "before": before,
                    "after": record["state"],
                }
                pending(db, run_id, "learner_state", candidate)
                # Merge against the locked, latest state rather than overwriting an earlier snapshot.
                levels[activity.difficulty] = record
                state.evidence, state.version = evidence, state.version + 1
                submission.assessment = {
                    "difficulty": activity.difficulty,
                    "correct": correct,
                    "hinted": activity.hinted,
                    "uncertain": uncertain,
                    "feedback": output.feedback,
                    "explanation": activity.private["explanation"],
                    "learnerVersion": state.version,
                    "assessmentId": submission.id,
                    "rubricCoverage": coverage,
                    "rubricScore": score,
                    "partial": partial,
                    "misconceptions": [m.model_dump() for m in output.misconceptions],
                    "contradiction": contradiction,
                    "priorEvidenceIds": prior.get("assessmentIds", []),
                    "timing": timing,
                    "reasoning": reasoning,
                    "referenceAnswer": rubric_question.referenceAnswer,
                    "evidenceOutcome": record["lastTransition"]["outcome"],
                    "confirmedWeakness": record.get("confirmedWeakness", {}).get("status")
                    == "active",
                }
                activity.status = "assessed"
                activity.private = {
                    **activity.private,
                    "question": question,
                    "grounding": reviewed_receipt,
                }
                accept(
                    db,
                    run_id,
                    "learner_state",
                    {**candidate, "learnerVersion": state.version},
                )
                step(
                    db,
                    run_id,
                    "assessing",
                    "Assessment recorded",
                    "Repeated independent rubric failures confirmed a weakness. Developing progress and earlier evidence were retained."
                    if record["lastTransition"]["outcome"] == "confirmed_weakness"
                    else "Recovery evidence was saved; another independent qualifying response is needed."
                    if record["lastTransition"]["outcome"] == "recovery_progress"
                    else "Validated evidence and feedback were saved atomically.",
                    "record_assessment",
                    "completed",
                    artifacts=[
                        {
                            "id": submission.id,
                            "kind": "assessment",
                            "label": "Saved assessment evidence",
                            "status": "committed",
                        }
                    ],
                )
    with factory.begin() as db:
        run_status(
            db,
            run_id,
            "waiting_for_learner",
            "Assessment ready. Review the analysis, then choose Next question when ready.",
        )
