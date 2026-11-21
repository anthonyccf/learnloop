"""Run separately: python -m learnloop.worker. Jobs survive API/worker restarts."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from threading import Event

from filelock import FileLock, Timeout
from sqlalchemy import and_, or_, select, text

from learnloop.core.config import get_settings
from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Job, Run, now, session_factory
from learnloop.runtime.events import run_status
from learnloop.runtime.workflows import execute, record_failure
from learnloop.runtime.cancellation import RunStopped
from learnloop.services.clients import Services

logger = logging.getLogger("learnloop.runtime.worker")
WORKFLOWS = ("course_preparation", "next_activity", "assessment")


def work_once(factory, services, workflow=None):
    engine = factory.kw["bind"]
    if engine.dialect.name == "sqlite":
        # OS-backed lock covers the whole job, including model calls and expired
        # leases. It is automatically released after a crash; a second worker
        # cannot execute the same job while the first is still alive.
        path = engine.url.database
        if path in (None, "", ":memory:"):
            raise ValueError("The SQLite worker requires a file-backed database")
        lock = FileLock(str(path) + ".worker.lock")
        try:
            lock.acquire(timeout=0)
        except Timeout:
            return False
        try:
            return _work_once(factory, services, workflow)
        finally:
            lock.release()
    return _work_once(factory, services, workflow)


def _work_once(factory, services, workflow=None):
    settings = services.settings
    sqlite = factory.kw["bind"].dialect.name == "sqlite"
    # Hold the advisory lock before counting an attempt, including lease recovery.
    with factory.kw["bind"].connect() as guard:
        locked_run = None
        try:
            with factory.begin() as db:
                query = (
                    select(Job)
                    .where(
                        or_(
                            and_(Job.status == "queued", or_(Job.lease_until.is_(None), Job.lease_until <= now())),
                            and_(Job.status == "running", Job.lease_until < now()),
                        )
                    )
                    .order_by(Job.id)
                    .with_for_update(skip_locked=True, of=Job)
                    .limit(1)
                )
                if workflow is not None:
                    query = query.join(Run, Run.id == Job.run_id).where(
                        Run.snapshot["workflow"].as_string() == workflow
                    )
                job = db.scalar(query)
                if not job:
                    return False
                run_id = job.run_id
                locked = True
                if not sqlite:
                    locked = guard.scalar(
                        text("SELECT pg_try_advisory_lock(hashtext(:id))"), {"id": run_id}
                    )
                    guard.commit()
                if not locked:
                    return False
                locked_run = run_id
                run = db.get(Run, run_id)
                if run.snapshot["status"] in ("completed", "waiting_for_learner", "stopped"):
                    job.status = "done"
                    return True
                if run.snapshot["workflow"] == "course_preparation":
                    run.input = {**run.input, "_cooperative_stop": True,
                                 "_expert_usage_enabled": True,
                                 "_expert_usage_prior_unknown": run.input.get("_expert_usage_prior_unknown", job.attempts > 0 and not run.input.get("_expert_usage_enabled"))}
                exhausted = job.attempts >= settings.worker_max_attempts
                if exhausted:
                    job.status = "failed"
                else:
                    job.status, job.attempts, job.lease_until = (
                        "running",
                        job.attempts + 1,
                        now() + timedelta(seconds=settings.worker_lease_seconds),
                    )
            if exhausted:
                with factory.begin() as db:
                    run_status(
                        db,
                        run_id,
                        "failed",
                        "The run reached its attempt limit. Inspect saved work before starting a new run.",
                    )
                return True
            try:
                execute(factory, services, run_id)
                with factory.begin() as db:
                    job = db.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
                    run = db.get(Run, run_id)
                    job.status = "paused" if run.snapshot["status"] == "paused" else "done"
                    job.lease_until = None
            except RunStopped:
                with factory.begin() as db:
                    job = db.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
                    job.status, job.lease_until = "done", None
                    run_status(db, run_id, "stopped", "Stopped by user. Saved work is retained.")
            except ServiceError as exc:
                try:
                    record_failure(factory, run_id, exc, settings.worker_max_attempts, settings.worker_retry_delay_seconds)
                except RunStopped:
                    with factory.begin() as db:
                        job = db.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
                        job.status, job.lease_until = "done", None
                        run_status(db, run_id, "stopped", "Stopped by user. Saved work is retained.")
            except Exception as exc:
                # Exception strings can contain SQL parameters or provider content.
                logger.error("Run %s failed (%s)", run_id, type(exc).__name__)
                try:
                    record_failure(
                        factory, run_id,
                        ServiceError("processing_failed", "Processing was interrupted. Retry from the saved checkpoint."),
                        settings.worker_max_attempts, settings.worker_retry_delay_seconds,
                    )
                except RunStopped:
                    with factory.begin() as db:
                        job = db.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
                        job.status, job.lease_until = "done", None
                        run_status(db, run_id, "stopped", "Stopped by user. Saved work is retained.")
            return True
        finally:
            if locked_run and not sqlite:
                guard.execute(text("SELECT pg_advisory_unlock(hashtext(:id))"), {"id": locked_run})
                guard.commit()


def work_loop(factory, services, workflow, stop):
    logger.info("Worker lane ready: %s", workflow)
    while not stop.is_set():
        if not work_once(factory, services, workflow):
            stop.wait(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument(
        "--workflow",
        choices=WORKFLOWS,
        action="append",
        help="Run only this workflow lane (repeatable; defaults to all three)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    services, factory = Services(get_settings()), session_factory()
    if args.once:
        if args.workflow and len(set(args.workflow)) != 1:
            parser.error("--once accepts at most one workflow")
        work_once(factory, services, args.workflow[0] if args.workflow else None)
        return
    workflows = tuple(dict.fromkeys(args.workflow or WORKFLOWS))
    stop = Event()
    if factory.kw["bind"].dialect.name == "sqlite":
        logger.info("SQLite worker ready: processing one job at a time")
        while not stop.is_set():
            did_work = False
            for workflow in workflows:
                did_work = work_once(factory, services, workflow) or did_work
            if not did_work:
                stop.wait(1)
        return
    with ThreadPoolExecutor(max_workers=len(workflows), thread_name_prefix="worker") as pool:
        futures = [
            pool.submit(work_loop, factory, services, workflow, stop) for workflow in workflows
        ]
        # Surface any lane failure instead of silently leaving part of the queue unattended.
        try:
            for future in as_completed(futures):
                future.result()
        finally:
            stop.set()


if __name__ == "__main__":
    main()
