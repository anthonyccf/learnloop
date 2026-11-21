"""Activity HTTP endpoints; registered by the application factory."""

import asyncio
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from learnloop.api.dependencies import ApiContext
from learnloop.core.schemas import (
    RunCommand,
)
from learnloop.persistence.database import (
    Command,
    Course,
    ExpertUsageCall,
    Job,
    Run,
    RunEvent,
)
from learnloop.runtime.events import run_status


def stop_expert_job(db, run_id, *, allow_finished=False):
    job = db.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
    run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run.snapshot.get("workflow") != "course_preparation":
        raise HTTPException(404, "Expert run not found.")
    if run.snapshot["status"] not in ("queued", "running", "paused"):
        if allow_finished:
            return {"status": run.snapshot["status"]}
        raise HTTPException(409, "This run has already stopped or finished.")
    if run.input.get("_stop_requested"):
        return {"status": "stopping"}
    if not job:
        raise HTTPException(409, "No worker job exists for this run.")
    if job.status == "running":
        if not run.input.get("_cooperative_stop"):
            raise HTTPException(409, "This run started on an older worker and cannot be stopped safely. Restart the worker after it finishes to enable stopping future runs.")
        run_status(db, run_id, "running", "Stopping after current requests finish. Saved work is retained.")
        run.input = {**run.input, "_stop_requested": True}
        return {"status": "stopping"}
    job.status, job.lease_until = "done", None
    run.input = {**run.input, "_stop_requested": True}
    run_status(db, run_id, "stopped", "Stopped by user. Saved work is retained.")
    return {"status": "stopped"}


def build_router(context: ApiContext):
    router = APIRouter(tags=["Activity"])
    factory = context.factory
    lock_course = context.lock_course
    owned = context.owned
    owner = context.owner
    settings = context.settings

    @router.get("/api/courses/{course_id}/runs")
    def list_runs(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            calls_by_run = {}
            for run_id, data in db.execute(select(ExpertUsageCall.run_id, ExpertUsageCall.data).join(Run, Run.id == ExpertUsageCall.run_id).where(Run.course_id == course_id, Run.owner_id == principal)):
                calls_by_run.setdefault(run_id, []).append(data)

            def expert_usage(run):
                if not run.input.get("_expert_usage_enabled"):
                    return None
                calls = calls_by_run.get(run.id, [])
                known = [call["costUsd"] for call in calls if call.get("costUsd") is not None]
                return {"reportedCostUsd": sum(known), "reportedCalls": len(known),
                        "unreportedCalls": len(calls) - len(known),
                        "priorUsageUnknown": bool(run.input.get("_expert_usage_prior_unknown"))}
            return [
                {
                    "id": r.id,
                    "workflow": r.snapshot["workflow"],
                    "status": r.snapshot["status"],
                    "summary": r.snapshot["summary"],
                    "startedAt": r.input.get("_started_at")
                    or next((e["at"] for e in r.snapshot.get("events", [])), None),
                    "documentId": (r.input.get("_inspection_document_ids") or [r.input.get("document_id")])[0],
                    "documentIds": r.input.get("_inspection_document_ids", []),
                    "hierarchyMode": r.input.get("hierarchy_mode", "continue") if r.snapshot["workflow"] == "course_preparation" else None,
                    "sessionId": r.input.get("session_id"),
                    "templateName": (r.input.get("prompt_template") or {}).get("name"),
                    "model": (r.input.get("prompt_template") or {}).get("model"),
                    "temperature": (r.input.get("prompt_template") or {}).get("temperature"),
                    "stopSupported": bool(r.input.get("_cooperative_stop")) or r.snapshot["status"] in ("queued", "paused"),
                    "expertUsage": expert_usage(r) if r.snapshot["workflow"] == "course_preparation" else None,
                    "modelsUsed": r.input.get("_models_used", []),
                }
                for r in db.scalars(
                    select(Run).where(Run.course_id == course_id, Run.owner_id == principal)
                )
            ]

    @router.get("/api/agent-activity/runs/{run_id}")
    def get_run(run_id: str, principal=Depends(owner)):
        with factory() as db:
            return owned(db, Run, run_id, principal).snapshot

    @router.post("/api/agent-activity/runs/{run_id}/stop")
    def stop_expert_run(run_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            owned(db, Run, run_id, principal)
            return stop_expert_job(db, run_id)

    @router.get("/api/agent-activity/runs/{run_id}/evaluation")
    def evaluate_run(run_id: str, principal=Depends(owner)):
        with factory() as db:
            run = owned(db, Run, run_id, principal)
            if run.snapshot.get("workflow") != "course_preparation":
                raise HTTPException(404, "Expert run not found.")
            job = db.scalar(select(Job).where(Job.run_id == run.id))
            views = run.input.get("_inspection_snapshots") or {}
            document_ids = run.input.get("_inspection_document_ids") or []
            view = views.get(document_ids[0]) if document_ids else None
            started = run.input.get("_started_at")
            terminal_events = [event for event in run.snapshot.get("events", [])
                               if event.get("type") == "run.status" and event.get("payload", {}).get("status") in ("completed", "failed", "needs_review", "paused")]
            elapsed = None
            if started and terminal_events and run.snapshot.get("status") in ("completed", "failed", "needs_review", "paused"):
                try:
                    elapsed = max(0, (datetime.fromisoformat(terminal_events[-1]["at"]) - datetime.fromisoformat(started)).total_seconds())
                except (ValueError, TypeError, KeyError):
                    pass
            result = {"runId": run.id, "snapshotAvailable": view is not None, "elapsedSeconds": elapsed,
                      "retriesUsed": max(0, job.attempts - 1) if job else None,
                      "concepts": None, "conceptsWithSourceLinks": None, "processedPassages": None,
                      "totalPassages": None, "reviewPassRate": None, "cost": None}
            if view is not None:
                graph = view.get("graph") or {}
                concepts = graph.get("concepts") or []
                chunk_ids = {chunk.get("id") for chunk in view.get("chunks", [])}
                result["concepts"] = len(concepts)
                result["conceptsWithSourceLinks"] = sum(
                    bool((set(concept.get("sourceChunkIds") or []) | {source.get("chunkId") for source in concept.get("sources", [])}) & chunk_ids)
                    for concept in concepts
                )
                coverage = graph.get("coverage") or {}
                result["processedPassages"] = coverage.get("processedPassages")
                result["totalPassages"] = coverage.get("totalPassages")
            return result

    @router.post("/api/agent-activity/runs/{run_id}/commands")
    def command(run_id: str, body: RunCommand, principal=Depends(owner)):
        with factory.begin() as db:
            run = owned(db, Run, run_id, principal)
            lock_course(db, run.course_id)
            run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
            db.refresh(run)
            existing = db.scalar(
                select(Command).where(
                    Command.owner_id == principal,
                    Command.operation_id == body.operationId,
                )
            )
            if existing:
                if existing.run_id != run_id or existing.body != body.model_dump():
                    raise HTTPException(409, "Operation ID already belongs to a different command.")
                return existing.receipt
            job = db.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
            if (
                body.expectedVersion != run.snapshot["recordVersion"]
                or body.kind not in run.snapshot["allowedCommands"]
                or job.attempts >= settings.worker_max_attempts
            ):
                raise HTTPException(
                    409, "Command is stale, unavailable, or exhausted. Refresh the run."
                )
            if body.kind == "resume" and not settings.generation_ready:
                raise HTTPException(409, "Configure the generation model before resuming.")
            receipt = {
                "runId": run.id,
                "operationId": body.operationId,
                "accepted": True,
            }
            db.add(
                Command(
                    owner_id=principal,
                    operation_id=body.operationId,
                    run_id=run_id,
                    body=body.model_dump(),
                    receipt=receipt,
                )
            )
            job.status, job.lease_until = "queued", None
            run_status(
                db,
                run_id,
                "queued",
                "Command accepted. Waiting for the worker to continue.",
            )
            return receipt

    @router.get("/api/agent-activity/runs/{run_id}/events")
    async def stream(
        run_id: str,
        request: Request,
        after_sequence: int = Query(default=0, ge=0),
        last_event_id: Annotated[str | None, Header()] = None,
        principal=Depends(owner),
    ):
        cursor = after_sequence
        if last_event_id:
            if not last_event_id.isdecimal():
                raise HTTPException(400, "Last-Event-ID must be an event sequence number.")
            cursor = max(cursor, int(last_event_id))

        def read(after):
            with factory() as db:
                run = owned(db, Run, run_id, principal)
                if after > run.snapshot["lastSequence"]:
                    raise HTTPException(
                        409,
                        "The event cursor is ahead of the run. Fetch a fresh snapshot.",
                    )
                events = list(
                    db.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
                        .order_by(RunEvent.sequence)
                        .limit(100)
                    )
                )
                return (
                    [event.data for event in events],
                    run.snapshot["status"],
                    run.snapshot["lastSequence"],
                )

        await asyncio.to_thread(read, cursor)

        async def messages():
            current, idle = cursor, 0
            for _ in range(600):
                if await request.is_disconnected():
                    break
                events, status, latest = await asyncio.to_thread(read, current)
                for event in events:
                    current = event["sequence"]
                    yield f"id: {current}\ndata: {json.dumps(event)}\n\n"
                if current >= latest and status in (
                    "completed",
                    "waiting_for_learner",
                    "needs_review",
                    "failed",
                    "paused",
                ):
                    break
                idle += 1
                if idle % 15 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            messages(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
