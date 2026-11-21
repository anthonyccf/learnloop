"""Resolve the Workbench generation requested by a pseudo-student test."""

import copy
import time

from fastapi import HTTPException
from sqlalchemy import select

from learnloop.evaluation.artifacts import digest, freeze
from learnloop.persistence.database import Chunk, Document, Run, RunHierarchy
from learnloop.pseudo_control import raise_if_stopped


def generated_snapshot(db, course_id, run):
    """Freeze a completed Workbench generation and its source passages for a test."""
    if run.course_id != course_id:
        raise HTTPException(422, "The Workbench run belongs to another course.")
    if (
        run.snapshot.get("workflow") != "course_preparation"
        or run.snapshot.get("status") != "completed"
    ):
        raise HTTPException(409, "Choose a completed Workbench course preparation run.")
    saved = db.get(RunHierarchy, run.id)
    if not saved or not saved.ready:
        raise HTTPException(409, "This Workbench run has no ready generated materials.")
    documents = copy.deepcopy(saved.documents)
    if not documents:
        raise HTTPException(409, "This Workbench run contains no generated materials.")
    document_ids = [item["id"] for item in documents]
    current = {
        item.id: item
        for item in db.scalars(
            select(Document).where(Document.course_id == course_id, Document.id.in_(document_ids))
        )
    }
    if len(current) != len(document_ids) or any(
        current[item["id"]].sha256 != item["sha256"] for item in documents
    ):
        raise HTTPException(
            409,
            "The source files changed after this Workbench run. Run preparation again before testing its materials.",
        )
    chunks = {
        item.id: {
            "id": item.id,
            "document_id": item.document_id,
            "course_id": item.course_id,
            "page": item.page,
            "text": item.text,
            "label": next(doc["filename"] for doc in documents if doc["id"] == item.document_id),
        }
        for item in db.scalars(
            select(Chunk)
            .where(Chunk.course_id == course_id, Chunk.document_id.in_(document_ids))
            .order_by(Chunk.id)
        )
    }
    payload = {
        "format": 1,
        "graph": copy.deepcopy(saved.graph),
        "documents": documents,
        "chunks": chunks,
    }
    transcripts = {
        id: text
        for document in documents
        for pack in document.get("graph", {}).get("resources", {}).values()
        for id, text in pack.get("slideEvidence", {}).items()
        if id in chunks
    }
    if transcripts:
        payload["slideEvidence"] = transcripts
    return payload, run, int(run.input.get("hierarchy_revision") or 0)


def material_fields(generated, source_run, revision, document_id):
    generated_documents = generated["documents"]
    generated_by_id = {doc["id"]: doc for doc in generated_documents}
    if document_id == "__all__":
        material = {
            "id": "__all__",
            "filename": "All Workbench-generated materials",
            "documentCount": len(generated_documents),
            "sha256": digest(sorted((d["id"], d["sha256"]) for d in generated_documents)),
        }
    elif document_id in generated_by_id:
        document = generated_by_id[document_id]
        material = {
            "id": document["id"],
            "filename": document["filename"],
            "sha256": document["sha256"],
        }
    else:
        raise HTTPException(422, "Choose a material from the selected Workbench run.")
    release = {
        "id": f"workbench:{source_run.id}:{revision}",
        "version": revision,
        "sha256": digest(generated),
    }
    return {"material": material, "release": release, "materialSource": "workbench_generated"}


def prepare_generated_input(path, pending, factory):
    setup = pending["setup"]
    while True:
        raise_if_stopped(path)
        with factory() as db:
            run = db.get(Run, setup["workbenchRunId"])
            if (
                not run
                or run.owner_id != pending["owner"]
                or run.course_id != setup["course"]["id"]
            ):
                raise HTTPException(404, "The course generation could not be found.")
            if run.snapshot["status"] == "completed":
                generated, _, revision = generated_snapshot(db, run.course_id, run)
                setup = {
                    **setup,
                    **material_fields(generated, run, revision, pending["documentId"]),
                }
                break
            if run.snapshot["status"] not in ("queued", "running", "paused"):
                raise HTTPException(
                    409,
                    run.snapshot.get("summary")
                    or "Course generation stopped before the materials were ready.",
                )
        time.sleep(3)
    data = {"setup": setup, "release": generated, "reused": None}
    freeze(pending["setupPath"], setup)
    freeze(path / "input.json", data)
    return data
