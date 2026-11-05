"""Persist only the public event projection, validated against frontend-generated schemas."""

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select

from learnloop.persistence.database import Job, Run, RunEvent, now, uid

CONTRACTS = json.loads(Path(__file__).with_name("agent-contract.schema.json").read_text())
VALIDATORS = {
    key: Draft202012Validator(value, format_checker=FormatChecker())
    for key, value in CONTRACTS.items()
}
ROLES = ("expert", "tutoring", "assessing")


def new_run(db, course, workflow: str, inputs: dict, concept_id=None):
    run_id = uid()
    snapshot = {
        "schemaVersion": 1,
        "id": run_id,
        "courseId": course.id,
        "workflow": workflow,
        "label": course.title,
        "status": "queued",
        "summary": "Waiting for the worker.",
        "recordVersion": 0,
        "lastSequence": 0,
        "checkpointId": run_id,
        "allowedCommands": [],
        "currentAgent": None,
        "agents": {
            role: {
                "role": role,
                "status": "not_started",
                "task": "Not needed yet",
                "detail": "This role runs when the workflow reaches its task.",
            }
            for role in ROLES
        },
        "validation": {"status": "not_requested", "summary": "No update proposed yet."},
        "committedChanges": [],
        "artifacts": [],
        "references": [],
        "events": [],
    }
    if concept_id:
        snapshot["conceptId"] = concept_id
    VALIDATORS["snapshot"].validate(snapshot)
    run = Run(
        id=run_id,
        course_id=course.id,
        owner_id=course.owner_id,
        input={**inputs, "_started_at": now().isoformat()},
        snapshot=snapshot,
    )
    db.add(run)
    db.flush()
    db.add(Job(run_id=run.id))
    return run


def emit(db, run_id: str, event_type: str, payload: dict):
    run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
    db.refresh(run)
    snapshot = copy.deepcopy(run.snapshot)
    sequence = snapshot["lastSequence"] + 1
    event = {
        "schemaVersion": 1,
        "id": uid(),
        "runId": run.id,
        "courseId": run.course_id,
        "sequence": sequence,
        "at": now().isoformat(),
        "type": event_type,
        "payload": payload,
    }
    VALIDATORS["event"].validate(event)
    if event_type == "agent.step":
        role = payload["role"]
        snapshot["agents"][role] = {
            key: value for key, value in payload.items() if key not in ("artifacts", "references")
        }
        if payload["status"] in ("running", "waiting_for_validation"):
            snapshot["currentAgent"] = role
        elif snapshot["currentAgent"] == role:
            snapshot["currentAgent"] = None
        for field in ("artifacts", "references"):
            if field in payload:

                def identity(item):
                    return (
                        item["id"]
                        if field == "artifacts"
                        else (
                            item["documentId"],
                            item.get("page"),
                            item.get("conceptId"),
                        )
                    )

                snapshot[field] = list(
                    {identity(item): item for item in snapshot[field] + payload[field]}.values()
                )[-100:]
    elif event_type == "agent.handoff":
        role = payload["to"]
        snapshot["currentAgent"] = role
        snapshot["agents"][role].update(
            status="queued", task="Handoff received", detail=payload["reason"]
        )
    elif event_type == "run.status":
        snapshot.update(payload)
        snapshot.pop("error", None)
        if payload.get("error"):
            snapshot["error"] = payload["error"]
        if payload["status"] not in ("queued", "running"):
            snapshot["currentAgent"] = None
    else:
        validation = snapshot["validation"]
        if payload["status"] in ("accepted", "rejected"):
            if validation["status"] != "pending" or validation["scope"] != payload["scope"]:
                raise ValueError("Validation must match a pending proposal")
        if payload["status"] == "accepted":
            if (
                payload["previousVersion"] != snapshot["recordVersion"]
                or payload["newVersion"] != snapshot["recordVersion"] + 1
            ):
                raise ValueError("Stale runtime version")
            if payload["scope"] == "learner_state":
                committed = payload["committed"]
                if any(committed[key] != value for key, value in validation["candidate"].items()):
                    raise ValueError("Commit does not match candidate")
                snapshot["committedChanges"].append(committed)
            snapshot["recordVersion"] = payload["newVersion"]
        snapshot["validation"] = {
            "status": payload["status"],
            "scope": payload["scope"],
            "summary": payload["summary"],
        }
        candidate = (
            payload.get("candidate")
            if payload["status"] == "pending"
            else validation.get("candidate")
        )
        if candidate:
            snapshot["validation"]["candidate"] = candidate
        if payload["status"] == "pending" and snapshot["currentAgent"]:
            snapshot["agents"][snapshot["currentAgent"]]["status"] = "waiting_for_validation"
    snapshot.update(
        lastSequence=sequence,
        lastEventId=event["id"],
        events=(snapshot["events"] + [event])[-1000:],
    )
    VALIDATORS["snapshot"].validate(snapshot)
    run.snapshot = snapshot
    db.add(RunEvent(id=event["id"], run_id=run.id, sequence=sequence, data=event))
    db.flush()
    return snapshot


def run_status(db, run_id, status, summary, commands=None, error=None):
    payload = {
        "status": status,
        "summary": summary,
        "allowedCommands": commands or [],
        "checkpointId": run_id,
    }
    if error:
        payload["error"] = error
    return emit(db, run_id, "run.status", payload)


def step(db, run_id, role, task, detail, tool=None, status="running", **kwargs):
    payload = {"role": role, "status": status, "task": task, "detail": detail, **kwargs}
    if tool:
        payload["tool"] = tool
    return emit(db, run_id, "agent.step", payload)


def pending(db, run_id, scope, candidate=None):
    payload = {
        "status": "pending",
        "scope": scope,
        "summary": "Checking sources, constraints and authoritative state.",
    }
    if candidate:
        payload["candidate"] = candidate
    return emit(db, run_id, "runtime.validation", payload)


def accept(db, run_id, scope, committed=None):
    version = db.get(Run, run_id).snapshot["recordVersion"]
    payload = {
        "status": "accepted",
        "scope": scope,
        "summary": "Validated output saved successfully.",
        "previousVersion": version,
        "newVersion": version + 1,
    }
    if committed:
        payload["committed"] = committed
    return emit(db, run_id, "runtime.validation", payload)
