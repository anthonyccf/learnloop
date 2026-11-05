"""Shared workflow dispatch and recovery; each agent owns its own implementation.

The durable worker calls execute(); it never chooses educational content.
This is an explicit Python dispatcher, not a LangGraph StateGraph.
"""

from sqlalchemy import select

from learnloop.agents.assessing.agent import run as assess
from learnloop.agents.expert.agent import run as prepare
from learnloop.agents.tutoring.agent import run as tutor
from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Document, Job, Run
from learnloop.runtime.events import emit, run_status, step

WORKFLOW_HANDLERS = {
    "course_preparation": prepare,
    "next_activity": tutor,
    "assessment": assess,
}


def execute(factory, services, run_id):
    with factory() as db:
        run = db.get(Run, run_id)
        workflow = run.snapshot["workflow"]
    if not services.settings.generation_ready:
        with factory.begin() as db:
            run_status(
                db,
                run_id,
                "paused",
                "Configure the generation model, then resume this saved run.",
                ["resume"],
            )
        return
    WORKFLOW_HANDLERS[workflow](factory, services, run_id)


def record_failure(factory, run_id, error: ServiceError, max_attempts):
    with factory.begin() as db:
        run = db.get(Run, run_id)
        if error.details:
            inputs = dict(run.input)
            inputs["failureDiagnostics"] = error.details
            run.input = inputs
        job = db.scalar(select(Job).where(Job.run_id == run_id))
        retryable = error.retryable and job.attempts < max_attempts
        status = "failed" if error.retryable else "needs_review"
        if run.snapshot["validation"]["status"] == "pending":
            emit(
                db,
                run_id,
                "runtime.validation",
                {
                    "status": "rejected",
                    "scope": run.snapshot["validation"]["scope"],
                    "summary": error.message,
                    "retryable": retryable,
                },
            )
        role = run.snapshot["currentAgent"] or (
            "expert" if run.snapshot["workflow"] == "course_preparation" else "tutoring"
        )
        step(
            db,
            run_id,
            role,
            "Work interrupted",
            error.message,
            status="failed" if error.retryable else "needs_review",
            error={
                "code": error.code,
                "message": error.message,
                "retryable": retryable,
            },
        )
        run_status(
            db,
            run_id,
            status,
            error.message,
            ["retry"] if retryable else [],
            {"code": error.code, "message": error.message, "retryable": retryable},
        )
        if run.snapshot["workflow"] == "course_preparation":
            document = db.get(Document, run.input["document_id"])
            if not error.retryable and document.status != "published":
                document.status = "needs_review"
        job.status, job.lease_until = status, None
