"""Documents HTTP endpoints; registered by the application factory."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from learnloop.agents.expert.materials import (
    MATERIALS_VERSION,
    difficulty_complete,
    material_valid,
    public_materials,
)
from learnloop.api.dependencies import ApiContext
from learnloop.core.schemas import DocumentRename
from learnloop.persistence.database import (
    Chunk,
    Course,
    Document,
    Run,
)
from learnloop.persistence.releases import get_release, scope_fingerprint
from learnloop.runtime.events import new_run
from learnloop.services.slides import render_slide


def build_router(context: ApiContext):
    router = APIRouter(tags=["Documents"])
    factory = context.factory
    lock_course = context.lock_course
    owned = context.owned
    owner = context.owner
    settings = context.settings

    @router.post("/api/documents/{document_id}/rename")
    def rename_document(document_id: str, body: DocumentRename, principal=Depends(owner)):
        with factory.begin() as db:
            doc = owned(db, Document, document_id, principal)
            extension = ".pdf" if doc.filename.lower().endswith(".pdf") else ".txt"
            doc.filename = f"{body.title}{extension}"
            return {"id": doc.id, "filename": doc.filename}

    @router.post("/api/documents/{document_id}/analyze", status_code=202)
    def review_all_sections(document_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            doc = owned(db, Document, document_id, principal)
            course = lock_course(db, doc.course_id)
            db.refresh(doc)
            if doc.graph.get("analysis", {}).get("complete"):
                return {"status": "ready"}
            for run in db.scalars(select(Run).where(Run.course_id == doc.course_id)):
                if run.input.get("document_id") == doc.id and run.snapshot["status"] in (
                    "queued",
                    "running",
                    "paused",
                ):
                    return {"runId": run.id, "status": run.snapshot["status"]}
            run = new_run(
                db,
                course,
                "course_preparation",
                {
                    "document_id": doc.id,
                    "review_all_sections": True,
                },
            )
            return {"runId": run.id, "status": "queued"}

    @router.post("/api/documents/{document_id}/materials", status_code=202)
    def generate_materials(document_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            doc = owned(db, Document, document_id, principal)
            course = lock_course(db, doc.course_id)
            db.refresh(doc)
            if doc.status not in ("prepared", "published"):
                raise HTTPException(409, "Wait for course concepts to finish processing first.")
            chunks = {
                c.id: {"text": c.text}
                for c in db.scalars(select(Chunk).where(Chunk.document_id == doc.id))
            }
            release = get_release(db, doc.course_id)
            if (
                release
                and any(
                    d["id"] == doc.id and d["graph"] == doc.graph
                    for d in release.payload["documents"]
                )
                and all(
                    doc.graph.get("resources", {}).get(c["id"], {}).get("version")
                    == MATERIALS_VERSION
                    and material_valid(doc.graph.get("resources", {}).get(c["id"]), chunks)
                    and difficulty_complete(doc.graph.get("resources", {}).get(c["id"]))
                    and doc.graph["resources"][c["id"]].get("scopeFingerprint")
                    == scope_fingerprint(
                        doc.graph["resources"][c["id"]]["lesson"],
                        doc.graph.get("curriculum", {}).get("objectives", {}).get(c["id"]),
                    )
                    for c in doc.graph.get("concepts", [])
                )
            ):
                return {"status": "ready"}
            for run in db.scalars(select(Run).where(Run.course_id == doc.course_id)):
                if run.input.get("document_id") == doc.id and run.snapshot["status"] in (
                    "queued",
                    "running",
                    "paused",
                ):
                    return {"runId": run.id, "status": run.snapshot["status"]}
            run = new_run(db, course, "course_preparation", {"document_id": doc.id})
            return {"runId": run.id, "status": "queued"}

    @router.post("/api/courses/{course_id}/documents", status_code=202)
    def upload(course_id: str, file: UploadFile, principal=Depends(owner)):
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1][:240]
        if not filename.lower().endswith((".pdf", ".txt")):
            raise HTTPException(415, "Only text PDFs and UTF-8 .txt files are supported.")
        content = file.file.read(settings.max_upload_bytes + 1)
        if not content or len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "The file is empty or exceeds the configured size limit.")
        with factory.begin() as db:
            course = owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            digest = hashlib.sha256(content).hexdigest()
            existing = db.scalar(
                select(Document).where(Document.course_id == course_id, Document.sha256 == digest)
            )
            if existing:
                runs = db.scalars(select(Run).where(Run.course_id == course_id))
                run = next(r for r in runs if r.input.get("document_id") == existing.id)
                return {
                    "documentId": existing.id,
                    "runId": run.id,
                    "status": existing.status,
                    "duplicate": True,
                }
            doc = Document(
                course_id=course_id,
                filename=filename,
                sha256=digest,
                content=content,
                content_type="application/pdf"
                if filename.lower().endswith(".pdf")
                else "text/plain",
            )
            db.add(doc)
            db.flush()
            run = new_run(db, course, "course_preparation", {"document_id": doc.id})
            return {
                "documentId": doc.id,
                "runId": run.id,
                "status": "queued",
                "duplicate": False,
            }

    @router.get("/api/documents/{document_id}/pages/{page}")
    def source_page(document_id: str, page: int, principal=Depends(owner)):
        with factory() as db:
            doc = owned(db, Document, document_id, principal)
            chunks = list(
                db.scalars(
                    select(Chunk)
                    .where(Chunk.document_id == doc.id, Chunk.page == page)
                    .order_by(Chunk.ordinal)
                )
            )
            if not chunks:
                raise HTTPException(404, "Page has no extracted passages.")
            return {
                "documentId": doc.id,
                "filename": doc.filename,
                "page": page,
                "passages": [{"chunkId": c.id, "text": c.text} for c in chunks],
            }

    @router.get("/api/documents/{document_id}/pages/{page}/slide")
    def slide_image(document_id: str, page: int, principal=Depends(owner)):
        with factory() as db:
            doc = owned(db, Document, document_id, principal)
            if doc.content_type != "application/pdf":
                raise HTTPException(415, "This material is text-only. Use the extracted text view.")
            if page < 1 or page > doc.pages:
                raise HTTPException(404, "Slide not found.")
            content = doc.content
        return Response(
            render_slide(content, page),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/api/documents/{document_id}/review")
    def document_review(document_id: str, principal=Depends(owner)):
        with factory() as db:
            doc = owned(db, Document, document_id, principal)
            graph = {key: value for key, value in doc.graph.items() if key != "resources"}
            chunks = {
                c.id: {"text": c.text}
                for c in db.scalars(select(Chunk).where(Chunk.document_id == doc.id))
            }
            return {
                "documentId": doc.id,
                "status": doc.status,
                "resources": graph,
                "learningMaterials": public_materials(doc, source_chunks=chunks),
            }

    return router
