"""Durable agent handoff requests stored with their worker run."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requestId: str = Field(min_length=1, max_length=100)
    parentRunId: str | None
    sessionId: str
    stepId: str | None
    courseReleaseId: str
    conceptId: str
    difficulty: Literal["basic", "intermediate", "advanced"]
    targetAgent: Literal["assessing", "expert"]
    task: str
    input: dict


def handoff_view(run, submission=None):
    request = run.input.get("handoff")
    if not request:
        return None
    status = run.snapshot["status"]
    completed = bool(submission and submission.assessment)
    return {
        "request": request,
        "runId": run.id,
        "status": "completed" if completed else status,
        "summary": run.snapshot.get("summary", ""),
        "result": {"assessmentId": submission.id, "learnerVersion": submission.assessment.get("learnerVersion")} if completed else None,
        "retryable": bool(set(run.snapshot.get("allowedCommands", [])) & {"retry", "resume"}),
    }
