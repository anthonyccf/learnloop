"""Activity HTTP endpoints; registered by the application factory."""

import asyncio
import json
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
    Job,
    Run,
    RunEvent,
)
from learnloop.runtime.events import run_status


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
            return [
                {
                    "id": r.id,
                    "workflow": r.snapshot["workflow"],
                    "status": r.snapshot["status"],
                    "summary": r.snapshot["summary"],
                    "startedAt": r.input.get("_started_at")
                    or next((e["at"] for e in r.snapshot.get("events", [])), None),
                    "documentId": r.input.get("document_id"),
                    "sessionId": r.input.get("session_id"),
                }
                for r in db.scalars(
                    select(Run).where(Run.course_id == course_id, Run.owner_id == principal)
                )
            ]

    @router.get("/api/agent-activity/runs/{run_id}")
    def get_run(run_id: str, principal=Depends(owner)):
        with factory() as db:
            return owned(db, Run, run_id, principal).snapshot

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
