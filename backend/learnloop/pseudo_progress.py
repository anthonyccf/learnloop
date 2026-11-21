"""Public progress projection from exploratory episode artifacts.

Never return simulator hidden knowledge, answers or held-out test content.
"""

import json

from learnloop.evaluation.artifacts import digest, thaw


def progress(path, setup, job, job_status):
    conditions = (
        ("adaptive", "fixed_sequence", "memory_free")
        if job["config"].get("baselines")
        else ("adaptive",)
    )
    unit_path = path / "unit.json"
    titles = {}
    if unit_path.is_file():
        unit = thaw(unit_path)["payload"]
        titles = {c["id"]: c["title"] for c in unit["graph"]["concepts"]}
    items = []
    for learner in setup.get("learners") or []:
        for condition in conditions:
            episode_root = path / "episodes" / digest([learner["id"], condition])[:16]
            retries = sorted((episode_root / "retries").glob("attempt-*"))
            root = retries[-1] if retries else episode_root
            result_path, trace_path = root / "result.json", root / "trace.json"
            checkpoint_path = root / "hidden" / "checkpoint.json"
            result = thaw(result_path)["payload"] if result_path.is_file() else None
            if trace_path.is_file():
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
            elif checkpoint_path.is_file():
                trace = json.loads(checkpoint_path.read_text(encoding="utf-8")).get("trace", [])
            else:
                trace = []
            events, milestones, first, level_counts = [], [], set(), {}
            for step in trace:
                selected = step.get("selected") or {}
                concept_id = selected.get("conceptId")
                level = step.get("difficulty")
                activity = int(step["index"]) + 1
                label = titles.get(concept_id, selected.get("title", concept_id))
                event = {
                    "activity": activity,
                    "concept": label,
                    "difficulty": level,
                    "before": step.get("before"),
                    "after": step.get("after"),
                    "correct": step.get("correct"),
                    "hinted": step.get("hinted"),
                    "session": step.get("session", 0) + 1,
                    "boundaryReset": bool(step.get("boundaryReset")),
                }
                events.append(event)
                key = (concept_id, level)
                level_counts[key] = level_counts.get(key, 0) + 1
                if (
                    step.get("after") == "demonstrated"
                    and step.get("before") != "demonstrated"
                    and key not in first
                ):
                    first.add(key)
                    milestones.append(
                        {
                            "concept": label,
                            "difficulty": level,
                            "activity": activity,
                            "levelActivities": level_counts[key],
                        }
                    )
            exam_progress = None
            exam_path = root / "exam-progress.json"
            if result is None and exam_path.is_file():
                saved = json.loads(exam_path.read_text(encoding="utf-8"))
                if saved.get("phase") in ("pre", "post") and isinstance(saved.get("total"), int):
                    exam_progress = {
                        "phase": saved["phase"],
                        "completed": int(saved.get("completed") or 0),
                        "total": saved["total"],
                    }
            metrics = (result or {}).get("metrics") or {}
            attempt_usage = (result or {}).get("usage") or metrics
            retry_status_path = root / "retry-status.json"
            retry_status = (
                json.loads(retry_status_path.read_text(encoding="utf-8"))
                if retry_status_path.is_file()
                else {}
            )
            status = (
                result["status"]
                if result
                else (
                    "in_progress"
                    if root.exists()
                    and (
                        job_status == "running"
                        or retry_status.get("status") in ("starting", "running")
                    )
                    else retry_status["status"]
                    if retry_status.get("status") == "failed"
                    else "not_started"
                    if not root.exists()
                    else "interrupted"
                )
            )
            previous_attempts = []
            for number, attempt in enumerate([episode_root, *retries[:-1]], 1) if retries else []:
                earlier = (
                    thaw(attempt / "result.json")["payload"]
                    if (attempt / "result.json").is_file()
                    else {}
                )
                earlier_trace = (
                    json.loads((attempt / "trace.json").read_text(encoding="utf-8"))
                    if (attempt / "trace.json").is_file()
                    else []
                )
                previous_attempts.append(
                    {
                        "attempt": number,
                        "status": earlier.get("status", "interrupted"),
                        "errorType": earlier.get("errorType"),
                        "activitiesCompleted": len(earlier_trace),
                    }
                )
            items.append(
                {
                    "learnerId": learner["id"],
                    "learnerName": learner["name"],
                    "condition": condition,
                    "status": status,
                    "errorType": (result or {}).get("errorType") or retry_status.get("errorType"),
                    "stopReason": (result or {}).get("stopReason"),
                    "attempt": len(retries) + 1,
                    "previousAttempts": previous_attempts,
                    "canRetry": job_status in ("completed", "completed_with_failures")
                    and status in ("failed", "budget_exhausted", "simulation_invalid")
                    and len(retries) < 2
                    and not (episode_root / "retry.lock").exists(),
                    "activityLimit": job["config"]["activities"],
                    "activitiesCompleted": len(events),
                    "examProgress": exam_progress,
                    "correctAnswers": sum(e["correct"] is True for e in events),
                    "hintsUsed": sum(e["hinted"] is True for e in events),
                    "milestones": milestones,
                    "activities": events,
                    "preScore": metrics.get("preScore"),
                    "postScore": metrics.get("postScore"),
                    "verifiedTargetActivities": metrics.get("activitiesAtVerifiedTarget"),
                    "postTestMasteredConcepts": metrics.get("postTestMasteredConcepts"),
                    "calls": attempt_usage.get("calls"),
                    "costUsd": attempt_usage.get("costUsd"),
                    "simulationPolicyAgreement": metrics.get("simulationPolicyAgreement"),
                }
            )
    return items
