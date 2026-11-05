"""Resume a failed pyramid in a new bounded run, preserving every accepted pack."""

import argparse
import copy
from contextlib import ExitStack
from datetime import timedelta

from filelock import FileLock
from sqlalchemy import select, text

from learnloop.core.config import get_settings
from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Course, Document, Job, Run, now, session_factory
from learnloop.runtime.events import new_run
from learnloop.runtime.workflows import execute, record_failure
from learnloop.services.clients import Services


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--concept")
    args = parser.parse_args()
    settings = get_settings()
    factory, services = session_factory(settings), Services(settings)
    with ExitStack() as resources:
        if settings.uses_sqlite:
            resources.enter_context(
                FileLock(str(factory.kw["bind"].url.database) + ".worker.lock", timeout=0)
            )
        guard = resources.enter_context(factory.kw["bind"].connect())
        with factory.begin() as db:
            previous = db.get(Run, args.run_id)
            if (
                not previous
                or previous.owner_id != settings.local_owner_id
                or not previous.input.get("rebuild_course")
            ):
                raise SystemExit("Expected a local-owner pyramid run.")
            if previous.snapshot["status"] not in ("failed", "needs_review"):
                raise SystemExit("Only an interrupted run can be resumed here.")
            inputs = copy.deepcopy(previous.input)
            docs = list(
                db.scalars(select(Document).where(Document.course_id == previous.course_id))
            )
            for doc in docs:
                for concept_id, issue in doc.graph.get("sourceIssues", {}).items():
                    if issue["code"] == "repeated_teaching":
                        inputs.setdefault("materialReviewFeedback", {}).setdefault(
                            concept_id, {"scopeFeedback": issue["message"]}
                        )
            if args.concept:
                if not any(args.concept in d.graph.get("sourceIssues", {}) for d in docs):
                    raise SystemExit("Expected a flagged concept in this course.")
                inputs.setdefault("materialReviewFeedback", {})[args.concept] = inputs.get(
                    "failureDiagnostics", {}
                )
            run = new_run(db, db.get(Course, previous.course_id), "course_preparation", inputs)
            run_id = run.id
            if not settings.uses_sqlite and not guard.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:id))"), {"id": run_id}
            ):
                raise SystemExit("Run is already owned by another worker.")
            guard.commit()
            job = db.scalar(select(Job).where(Job.run_id == run_id))
            job.status, job.attempts = "running", 1
            job.lease_until = now() + timedelta(seconds=settings.worker_lease_seconds)
        print("Resuming accepted checkpoints in run", run_id, flush=True)
        try:
            execute(factory, services, run_id)
            with factory.begin() as db:
                job = db.scalar(select(Job).where(Job.run_id == run_id))
                job.status, job.lease_until = "done", None
            print("Completed", run_id, flush=True)
        except ServiceError as error:
            record_failure(factory, run_id, error, settings.worker_max_attempts)
            print("Review required", error.code, error.message, flush=True)
        except Exception:
            record_failure(
                factory,
                run_id,
                ServiceError(
                    "processing_failed",
                    "Processing interrupted; accepted checkpoints are retained.",
                ),
                settings.worker_max_attempts,
            )
            raise
        finally:
            if not settings.uses_sqlite:
                guard.execute(text("SELECT pg_advisory_unlock(hashtext(:id))"), {"id": run_id})
                guard.commit()


if __name__ == "__main__":
    main()
