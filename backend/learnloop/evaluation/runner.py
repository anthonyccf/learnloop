import copy
import time
from datetime import UTC, datetime, timedelta

from learnloop.agents.rubrics import validate_assessment
from learnloop.core.domain import assess_evidence, effective_state, select_concept
from learnloop.core.planning import candidates
from learnloop.core.schemas import Assessment, PlanChoice, Question
from learnloop.evaluation.artifacts import (
    checkpoint,
    digest,
    freeze,
    public_question,
    runtime_hash,
    write,
)
from learnloop.evaluation.metrics import episode_metrics, latency_by_role
from learnloop.evaluation.provider import BudgetExhausted, usage
from learnloop.evaluation.simulator import Student, independent_score
from learnloop.evaluation.variants import instruction


def clock_evidence(evidence, at):
    normalized = copy.deepcopy(evidence)
    for levels in normalized.values():
        for record in levels.values():
            record["state"] = effective_state(record, at)
            record.pop(
                "reviewAt", None
            )  # Prevent the host wall clock affecting simulated selection.
    return normalized


def exam(bank, phase, student, provider, at):
    results = []
    for item in bank[phase]:
        reply, _ = student.respond(provider, item["conceptId"], item["question"], phase, at)
        score = independent_score(item["question"], reply)
        student.record_score(score["correct"])
        results.append(
            {
                "id": item["id"],
                "conceptId": item["conceptId"],
                "difficulty": item["question"]["difficulty"],
                **score,
            }
        )
    return results


def initialize(pre):
    evidence = {}
    for item in pre:
        evidence.setdefault(item["conceptId"], {})[item["difficulty"]] = {
            "state": "developing",
            "attempts": 1,
            "assisted": 0,
            "independentActivityIds": [],
            "assessmentIds": [item["id"]],
            "preTestScore": item["score"],
        }
    return evidence


def run_episode(
    unit,
    bank,
    artifact,
    variants,
    profile,
    repeat,
    baseline,
    config,
    provider,
    root,
    *,
    mode="research",
):
    concepts = artifact["graph"]["concepts"]
    if provider.offline:
        provider.max_calls = config.maxCalls
    wall_started = time.perf_counter()
    at = datetime(2030, 1, 1, tzinfo=UTC)
    student = Student(concepts, profile, config.seed, repeat)
    identity = {
        "variants": variants,
        "profile": profile,
        "repeat": repeat,
        "baseline": baseline,
        "config": config.model_dump(),
        "unitHash": digest(unit.model_dump()),
        "resourceHash": digest(artifact),
        "examHash": digest(bank),
        "mode": mode,
        "runtimeHash": runtime_hash(),
        "prompts": {
            role: instruction(role, variants[key])
            for role, key in [
                ("Expert", "expert"),
                ("Tutoring", "tutor"),
                ("Assessing", "assessor"),
            ]
        },
    }
    code_version = identity["runtimeHash"]
    write(root / "manifest.json", identity)
    initial_hidden = student.snapshot()
    evidence, trace, previous, seen, history = {}, [], None, set(), []
    predicted_misconceptions = set()
    violations = {
        "prerequisiteViolations": 0,
        "invalidUpdates": 0,
        "repeatedQuestions": 0,
        "recoveries": 0,
    }
    result = {
        "id": digest(identity),
        "configurationId": "-".join(variants.values()) + "-" + baseline,
        "variants": variants,
        "profile": profile,
        "repeat": repeat,
        "baseline": baseline,
        "mode": mode,
        "status": "failed",
    }
    try:
        pre = exam(bank, "pre", student, provider, at)
        initial = initialize(pre)
        evidence = copy.deepcopy(initial)
        write(root / "hidden" / "initial.json", initial_hidden)
        previous_session = 0
        plan = {}
        for index in range(config.activities):
            if runtime_hash() != code_version:
                raise ValueError("Runtime source changed during evaluation")
            session_index = min(config.sessions - 1, index * config.sessions // config.activities)
            boundary = session_index != previous_session
            previous_session = session_index
            if boundary:
                at += timedelta(days=config.sessionGapDays)
                if baseline == "memory_free":
                    evidence, history, plan = copy.deepcopy(initial), [], {}
                    previous = None
            observed = clock_evidence(evidence, at)
            options = candidates(artifact["graph"], observed, previous=previous)
            available = []
            for option in options:
                pack = artifact["materials"][option["conceptId"]]["content"]
                level = option["difficulty"]
                if baseline == "fixed_sequence":
                    tried = sum(id.startswith(option["conceptId"] + "|") for id in seen)
                    level = (
                        "basic",
                        "basic",
                        "intermediate",
                        "intermediate",
                        "advanced",
                        "advanced",
                    )[min(tried, 5)]
                pool = [
                    (i, q)
                    for i, q in enumerate(pack["tests"])
                    if q["difficulty"] == level and f"{option['conceptId']}|{i}" not in seen
                ]
                if pool:
                    available.append({**option, "difficulty": level, "poolIndex": pool[0][0]})
            if not available:
                result["stopReason"] = "no_eligible_frozen_activity"
                break
            if baseline == "fixed_sequence":
                order = {c["id"]: i for i, c in enumerate(concepts)}
                selected = min(available, key=lambda c: order[c["conceptId"]])
                rationale = "Fixed prerequisite-respecting catalog order and fixed level schedule."
            else:
                # Identical fields and tools across Tutor prompts; no hidden profile/post-test input.
                choice = provider.generate(
                    "Tutoring",
                    instruction("Tutoring", variants["tutor"]),
                    {
                        "goal": {
                            "description": "Develop independent understanding of this course unit."
                        },
                        "graph": artifact["graph"],
                        "evidence": observed,
                        "plan": plan,
                        "candidates": available,
                    },
                    PlanChoice,
                )
                selected = next((c for c in available if c["id"] == choice.candidateId), None)
                if selected is None:
                    raise ValueError("Model proposed a non-candidate action")
                rationale = choice.rationale
            id, level = selected["conceptId"], selected["difficulty"]
            if not select_concept(artifact["graph"], observed, id):
                violations["prerequisiteViolations"] += 1
                raise ValueError("Prerequisite violation")
            pack = artifact["materials"][id]["content"]
            question = Question.model_validate(pack["tests"][selected["poolIndex"]])
            q = question.model_dump()
            question_id = f"{id}|{selected['poolIndex']}"
            if question_id in seen:
                violations["repeatedQuestions"] += 1
                raise ValueError("Repeated frozen activity")
            lesson = (
                pack["basicLesson"]
                if level == "basic"
                else pack["advancedLesson"]
                if level == "advanced"
                else pack["lesson"]
            )
            # Teaching is an actual delivered artifact; no private keys/rubric/held-out text.
            teaching = (
                copy.deepcopy(lesson)
                if selected["action"] not in ("practice", "reassess")
                else None
            )
            reply, elapsed = student.respond(provider, id, q, "train", at, teaching)
            hinted = reply.hintRequested
            if hinted:
                reply, extra = student.respond(provider, id, q, "train", at, teaching, q["hint"])
                elapsed += extra
            at += timedelta(milliseconds=elapsed)
            prior = copy.deepcopy(evidence.get(id, {}).get(level, {}))
            context = {
                "question": public_question(q),
                "selectedChoiceId": reply.choiceId,
                "correct": reply.choiceId == q["correctChoiceId"],
                "hintUsed": hinted,
                "reasoning": reply.reasoning,
                "rubric": [c.model_dump() for c in question.rubric],
                "referenceAnswer": q["referenceAnswer"],
                "difficulty": level,
                "timing": {"responseTimeMs": elapsed, "basis": "simulated"},
                "priorEvidence": prior,
                "previousAssessments": history[-8:],
                "passages": [
                    {"chunkId": s, "text": unit.chunks()[s]["text"]}
                    for s in {r["chunkId"] for r in q["sources"]}
                ],
            }
            assessed = provider.generate(
                "Assessing", instruction("Assessing", variants["assessor"]), context, Assessment
            )
            coverage, score = validate_assessment(
                question, assessed, reply.choiceId, reply.reasoning
            )
            correct = reply.choiceId == question.correctChoiceId
            student.record_score(correct)
            before, record = assess_evidence(
                prior,
                question_id,
                correct and score >= 1,
                hinted,
                assessed.uncertain or (assessed.contradiction and correct and score >= 1),
                at,
            )
            if (
                record["state"] == "demonstrated"
                and before != "demonstrated"
                and (
                    not correct
                    or score < 1
                    or hinted
                    or assessed.uncertain
                    or len(record["independentActivityIds"]) < 2
                )
            ):
                violations["invalidUpdates"] += 1
                raise ValueError("Unsupported demonstration")
            if (
                record.get("lastTransition", {}).get("outcome") == "demonstration"
                and prior.get("confirmedWeakness", {}).get("status") == "active"
            ):
                violations["recoveries"] += 1
            record["assessmentIds"] = [*prior.get("assessmentIds", []), question_id]
            student.learn(
                provider,
                id,
                level,
                reply,
                teaching,
                {"feedback": assessed.feedback, "answerExplanation": question.explanation},
                at,
            )
            evidence.setdefault(id, {})[level] = record
            if assessed.misconceptions:
                predicted_misconceptions.add(id)
            seen.add(question_id)
            step = {
                "index": index,
                "session": session_index,
                "at": at.isoformat(),
                "candidates": available,
                "selected": selected,
                "rationale": rationale,
                "evidenceBefore": observed,
                "before": before,
                "after": record["state"],
                "questionId": question_id,
                "difficulty": level,
                "hinted": hinted,
                "correct": correct,
                "rubricScore": score,
                "uncertain": assessed.uncertain,
                "coverage": coverage,
                "responseTimeMs": elapsed,
                "boundaryReset": boundary and baseline == "memory_free",
            }
            trace.append(step)
            history.append(
                {
                    "conceptId": id,
                    "difficulty": level,
                    "questionId": question_id,
                    "correct": correct,
                    "uncertain": assessed.uncertain,
                    "rubricScore": score,
                    "misconceptions": [m.model_dump() for m in assessed.misconceptions],
                }
            )
            plan = {"version": len(trace), "selected": selected, "reason": rationale}
            previous = id
            checkpoint(
                root / "hidden" / "checkpoint.json",
                {
                    "evidence": evidence,
                    "student": student.snapshot(),
                    "plan": plan,
                    "at": at.isoformat(),
                    "trace": trace,
                },
            )
        post = exam(bank, "post", student, provider, at)
        if runtime_hash() != code_version:
            raise ValueError("Runtime source changed during held-out scoring")
        normalized = clock_evidence(evidence, at)
        result.update(
            status="completed",
            metrics=episode_metrics(
                pre,
                post,
                normalized,
                student.labels(at),
                student.misconceptions,
                predicted_misconceptions,
                concepts,
                len(trace),
                provider.calls,
                violations,
                config.postTarget,
            ),
            latencyByRole=latency_by_role(provider.calls),
        )
        result["metrics"]["simulationPolicyAgreement"] = student.adherence()
        result["profileControlValid"] = (
            student.adherence() is not None and student.adherence() >= config.minPolicyAgreement
        )
        if mode == "research" and not result["profileControlValid"]:
            result["status"] = "simulation_invalid"
        write(
            root / "hidden" / "outcome.json",
            {
                "initial": initial_hidden,
                "final": student.snapshot(),
                "pre": pre,
                "post": post,
                "estimatedEvidence": evidence,
            },
        )
    except Exception as error:
        result["status"] = "budget_exhausted" if isinstance(error, BudgetExhausted) else "failed"
        # Never persist provider error text (may echo private input or credentials).
        result["errorType"] = type(error).__name__
        result["usage"] = usage(provider.calls)
        checkpoint(
            root / "hidden" / "checkpoint.json",
            {"evidence": evidence, "student": student.snapshot(), "trace": trace},
        )
    write(root / "trace.json", trace)
    result["traceHash"] = digest(trace)
    result["endToEndLatencyMs"] = (time.perf_counter() - wall_started) * 1000
    result["usageLedger"] = provider.calls
    freeze(root / "result.json", result)
    return result
