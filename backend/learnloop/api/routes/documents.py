"""Documents HTTP endpoints; registered by the application factory."""

import hashlib
import json
from types import SimpleNamespace

from fastapi import APIRouter, Body, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select

from learnloop.agents.expert.materials import (
    MATERIALS_VERSION,
    material_valid,
    public_materials,
    starter_complete,
)
from learnloop.api.dependencies import ApiContext
from learnloop.core.schemas import DocumentAnalyzeRequest, DocumentRename
from learnloop.persistence.database import (
    Chunk,
    ChunkEmbedding,
    Course,
    Document,
    Run,
)
from learnloop.persistence.releases import get_release, scope_fingerprint
from learnloop.runtime.events import inspection_record_fingerprints, inspection_snapshots, new_run
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
    def review_all_sections(
        document_id: str,
        body: DocumentAnalyzeRequest | None = Body(default=None),
        principal=Depends(owner),
    ):
        with factory.begin() as db:
            doc = owned(db, Document, document_id, principal)
            course = lock_course(db, doc.course_id)
            db.refresh(doc)
            prompt_template = body.promptTemplate if body else None
            force = body.force if body else False
            if doc.graph.get("analysis", {}).get("complete") and not force and not prompt_template:
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
                    "inspection_changes_only": bool(force or prompt_template),
                },
            )
            if prompt_template or force:
                template_payload = prompt_template.model_dump() if prompt_template else None
                fingerprint_input = {"template": template_payload, "run_id": run.id}
                fingerprint = hashlib.sha256(
                    json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                run.input = {
                    **run.input,
                    "prompt_template": template_payload,
                    "prompt_template_fingerprint": fingerprint,
                }
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
                    and starter_complete(doc.graph.get("resources", {}).get(c["id"]))
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
    def upload(
        course_id: str,
        file: UploadFile,
        defer_processing: bool = Form(default=False),
        principal=Depends(owner),
    ):
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
                run = next((r for r in runs if r.input.get("document_id") == existing.id), None)
                if not defer_processing and run is None and not existing.graph.get("analysis", {}).get("complete"):
                    run = new_run(db, course, "course_preparation", {"document_id": existing.id})
                return {
                    "documentId": existing.id,
                    "runId": run.id if run else None,
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
            run = None if defer_processing else new_run(db, course, "course_preparation", {"document_id": doc.id})
            return {
                "documentId": doc.id,
                "runId": run.id if run else None,
                "status": "queued" if run else "uploaded",
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

    @router.get("/api/documents/{document_id}/inspection")
    def inspect_document(
        document_id: str,
        kind: str = "source_chunks",
        offset: int = 0,
        limit: int = 50,
        record_id: str | None = None,
        run_id: str | None = None,
        principal=Depends(owner),
    ):
        """Return a bounded, read-only view of Expert's saved document records."""
        if kind not in ("source_chunks", "concepts", "lessons", "questions", "embeddings"):
            raise HTTPException(422, "Choose a supported inspection record type.")
        if offset < 0 or limit < 1 or limit > 100:
            raise HTTPException(422, "Inspection pages must use an offset >= 0 and limit 1-100.")

        with factory() as db:
            doc = owned(db, Document, document_id, principal)
            view = None
            inspection_mode = "live"
            baseline = None
            if run_id:
                run = owned(db, Run, run_id, principal)
                if run.course_id != doc.course_id or run.snapshot.get("workflow") != "course_preparation":
                    raise HTTPException(404, "Run not found for this material.")
                if doc.id not in run.input.get("_inspection_document_ids", []):
                    raise HTTPException(409, "No inspection data is available for this run and material.")
                if run.snapshot.get("status") not in ("queued", "running", "paused"):
                    view = run.input.get("_inspection_snapshots", {}).get(doc.id)
                    if view is None:
                        raise HTTPException(409, "No saved inspection snapshot is available for this run. Snapshots are saved when new runs stop or finish.")
                    inspection_mode = "snapshot"
                baseline = run.input.get("_inspection_baselines", {}).get(doc.id)
                if baseline is not None and view is None:
                    view = inspection_snapshots(db, run).get(doc.id)
            graph = view["graph"] if view else doc.graph or {}
            doc_status = view["status"] if view else doc.status
            snapshot_chunks = [SimpleNamespace(**c) for c in view["chunks"]] if view else None
            snapshot_embeddings = {c.id: SimpleNamespace(**c.embedding) for c in snapshot_chunks if c.embedding} if view else None
            page_count = view["pages"] if view else doc.pages
            extracted_pages = {chunk.page for chunk in snapshot_chunks} if view else set(db.scalars(select(Chunk.page).where(Chunk.document_id == doc.id).distinct()))
            missing_text_pages = [page for page in range(1, page_count + 1) if page not in extracted_pages] if page_count and extracted_pages and doc.filename.lower().endswith(".pdf") else []
            concepts = graph.get("concepts", [])
            resources = graph.get("resources", {})
            chunk_count = len(snapshot_chunks) if view else db.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
            ) or 0
            embedding_count = len(snapshot_embeddings) if view else db.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(ChunkEmbedding.document_id == doc.id)
            ) or 0
            concept_by_id = {concept.get("id"): concept for concept in concepts}
            changed = None
            if baseline is not None:
                fingerprints = inspection_record_fingerprints(view)
                changed = {
                    category: {key for key, value in records.items() if baseline.get(category, {}).get(key) != value}
                    for category, records in fingerprints.items()
                }

            def source_ids(value):
                ids = set(value.get("sourceChunkIds", []))
                ids.update(
                    source.get("chunkId")
                    for source in value.get("sources", [])
                    if source.get("chunkId")
                )
                return ids

            lesson_items = []
            question_items = []
            for concept_id, pack in resources.items():
                concept = concept_by_id.get(concept_id, {})
                lesson = pack.get("lesson") or {}
                if lesson:
                    lesson_items.append(
                        {
                            "id": f"lesson:{concept_id}",
                            "conceptId": concept_id,
                            "conceptTitle": concept.get("title", concept_id),
                            "title": lesson.get("title", "Untitled lesson"),
                            "objective": lesson.get("objective", ""),
                            "version": pack.get("version"),
                            "status": doc_status,
                        }
                    )
                for index, question in enumerate(pack.get("tests", [])):
                    question_items.append(
                        {
                            "id": question.get("id") or f"{concept_id}:question:{index + 1}",
                            "conceptId": concept_id,
                            "conceptTitle": concept.get("title", concept_id),
                            "prompt": question.get("prompt", ""),
                            "difficulty": question.get("difficulty", "intermediate"),
                            "format": question.get("format", "single_choice"),
                            "status": doc_status,
                        }
                    )

            active_concept_ids = set(concept_by_id)
            saved_counts = {
                "source_chunks": chunk_count,
                "embeddings": embedding_count,
                "concepts": len(concepts),
                "lessons": sum(item["conceptId"] in active_concept_ids for item in lesson_items),
                "questions": sum(item["conceptId"] in active_concept_ids for item in question_items),
            }
            source_warning_count = len(active_concept_ids.intersection(graph.get("sourceIssues", {})))
            changed_lesson_concepts = {
                item["conceptId"] for item in lesson_items
                if changed is None or item["id"] in changed["lessons"]
            }
            visible_concepts = [
                c for c in concepts
                if changed is None or c.get("id") in changed["concepts"]
                or c.get("id") in changed_lesson_concepts
            ]
            if changed is not None:
                lesson_items = [item for item in lesson_items if item["id"] in changed["lessons"]]
                question_items = [item for item in question_items if item["id"] in changed["questions"]]
                visible_chunks = [c for c in snapshot_chunks if c.id in changed["source_chunks"]]
                visible_embeddings = [c for c in snapshot_chunks if c.id in changed["embeddings"]]
                chunk_count, embedding_count = len(visible_chunks), len(visible_embeddings)
            counts = {
                "source_chunks": chunk_count,
                "concepts": len(visible_concepts),
                "lessons": len(lesson_items),
                "questions": len(question_items),
                "embeddings": embedding_count,
            }
            if kind == "source_chunks":
                selected = (visible_chunks if changed is not None else snapshot_chunks)[offset:offset + limit] if view else list(
                    db.scalars(
                        select(Chunk)
                        .where(Chunk.document_id == doc.id)
                        .order_by(Chunk.ordinal)
                        .offset(offset)
                        .limit(limit)
                    )
                )
                embeddings = snapshot_embeddings if view else {
                    row.chunk_id: row
                    for row in db.scalars(
                        select(ChunkEmbedding).where(
                            ChunkEmbedding.document_id == doc.id,
                            ChunkEmbedding.chunk_id.in_([chunk.id for chunk in selected]),
                        )
                    )
                } if selected else {}
                items = [
                    {
                        "id": chunk.id,
                        "ordinal": chunk.ordinal,
                        "page": chunk.page,
                        "text": chunk.text,
                        "embedding": (
                            {
                                "model": embeddings[chunk.id].model,
                                "dimensions": embeddings[chunk.id].dimensions,
                            }
                            if chunk.id in embeddings
                            else None
                        ),
                    }
                    for chunk in selected
                ]
            elif kind == "embeddings":
                selected = [(c, snapshot_embeddings[c.id]) for c in (visible_embeddings if changed is not None else snapshot_chunks) if c.id in snapshot_embeddings][offset:offset + limit] if view else db.execute(
                    select(Chunk, ChunkEmbedding)
                    .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
                    .where(Chunk.document_id == doc.id)
                    .order_by(Chunk.ordinal)
                    .offset(offset)
                    .limit(limit)
                ).all()
                items = [
                    {
                        "id": chunk.id,
                        "ordinal": chunk.ordinal,
                        "page": chunk.page,
                        "model": embedding.model,
                        "dimensions": embedding.dimensions,
                        "stored": True,
                    }
                    for chunk, embedding in selected
                ]
            else:
                source = {
                    "concepts": [
                        {
                            "id": concept.get("id", ""),
                            "title": concept.get("title", "Untitled concept"),
                            "summary": concept.get("summary", ""),
                            "sourceCount": len(source_ids(concept)),
                            "sourceChunkIds": sorted(source_ids(concept)),
                            "lessonCount": sum(item["conceptId"] == concept.get("id") for item in lesson_items),
                            "questionCount": sum(item["conceptId"] == concept.get("id") for item in question_items),
                            "lesson": next((
                                {"id": item["id"], "title": item["title"], "objective": item["objective"]}
                                for item in lesson_items if item["conceptId"] == concept.get("id")
                            ), None),
                            "status": doc_status,
                        }
                        for concept in visible_concepts
                    ],
                    "lessons": lesson_items,
                    "questions": question_items,
                }[kind]
                items = source[offset : offset + limit]

            relationship = None
            page_content = None
            if record_id:
                if changed is not None and record_id not in changed[kind]:
                    raise HTTPException(404, "The selected record was not changed in this run.")
                selected_concept_ids = set()
                selected_title = record_id
                selected_question = None
                selected_lesson = None
                if kind == "source_chunks" or kind == "embeddings":
                    selected_chunk = next((c for c in snapshot_chunks if c.id == record_id), None) if view else db.scalar(
                        select(Chunk).where(
                            Chunk.document_id == doc.id, Chunk.id == record_id
                        )
                    )
                    if not selected_chunk:
                        raise HTTPException(404, "The selected source record was not found.")
                    selected_title = f"Source chunk · {record_id}"
                    if kind == "source_chunks":
                        page_chunks = [c for c in snapshot_chunks if c.page == selected_chunk.page] if view else list(
                            db.scalars(
                                select(Chunk)
                                .where(
                                    Chunk.document_id == doc.id,
                                    Chunk.page == selected_chunk.page,
                                )
                                .order_by(Chunk.ordinal)
                            )
                        )
                        page_content = {
                            "page": selected_chunk.page,
                            "chunks": [
                                {"id": chunk.id, "ordinal": chunk.ordinal, "text": chunk.text}
                                for chunk in page_chunks
                            ],
                        }
                    selected_concept_ids = {
                        concept.get("id")
                        for concept in concepts
                        if record_id in source_ids(concept)
                    }
                elif kind == "concepts":
                    concept = concept_by_id.get(record_id)
                    if not concept:
                        raise HTTPException(404, "The selected concept record was not found.")
                    selected_concept_ids = {record_id}
                    selected_title = concept.get("title", record_id)
                elif kind == "lessons":
                    for concept_id, pack in resources.items():
                        if f"lesson:{concept_id}" == record_id and pack.get("lesson"):
                            selected_lesson = pack["lesson"]
                            selected_concept_ids = {concept_id}
                            selected_title = selected_lesson.get("title", "Lesson")
                            break
                    if not selected_lesson:
                        raise HTTPException(404, "The selected lesson record was not found.")
                elif kind == "questions":
                    for concept_id, pack in resources.items():
                        for index, question in enumerate(pack.get("tests", [])):
                            question_id = question.get("id") or f"{concept_id}:question:{index + 1}"
                            if question_id == record_id:
                                selected_question = question
                                selected_concept_ids = {concept_id}
                                selected_title = question.get("prompt", "Question")
                                break
                        if selected_question:
                            break
                    if not selected_question:
                        raise HTTPException(404, "The selected question record was not found.")

                linked_concepts = [
                    concept for concept in concepts if concept.get("id") in selected_concept_ids
                ]
                linked_lessons = []
                linked_questions = []
                chunk_ids = {record_id} if kind in ("source_chunks", "embeddings") else set()
                for concept in linked_concepts:
                    concept_id = concept.get("id")
                    concept_chunk_ids = source_ids(concept)
                    chunk_ids.update(concept_chunk_ids)
                    pack = resources.get(concept_id, {})
                    lesson = pack.get("lesson") or {}
                    lesson_chunk_ids = source_ids(lesson) or concept_chunk_ids
                    if lesson and (changed is None or f"lesson:{concept_id}" in changed["lessons"]):
                        linked_lessons.append(
                            {
                                "id": f"lesson:{concept_id}",
                                "conceptId": concept_id,
                                "title": lesson.get("title", "Untitled lesson"),
                                "objective": lesson.get("objective", ""),
                                "sourceChunkIds": sorted(lesson_chunk_ids),
                            }
                        )
                        chunk_ids.update(lesson_chunk_ids)
                    for index, question in enumerate(pack.get("tests", [])):
                        question_chunk_ids = source_ids(question) or concept_chunk_ids
                        question_id = question.get("id") or f"{concept_id}:question:{index + 1}"
                        if changed is not None and question_id not in changed["questions"]:
                            continue
                        linked_questions.append(
                            {
                                "id": question_id,
                                "conceptId": concept_id,
                                "prompt": question.get("prompt", ""),
                                "difficulty": question.get("difficulty", "intermediate"),
                                "format": question.get("format", "single_choice"),
                                "sourceChunkIds": sorted(question_chunk_ids),
                            }
                        )
                        chunk_ids.update(question_chunk_ids)
                if selected_lesson:
                    selected_concept = concept_by_id[next(iter(selected_concept_ids))]
                    lesson_chunk_ids = source_ids(selected_lesson) or source_ids(selected_concept)
                    chunk_ids.update(lesson_chunk_ids)
                    for lesson_row in linked_lessons:
                        if lesson_row["id"] == record_id:
                            lesson_row["sourceChunkIds"] = sorted(lesson_chunk_ids)
                if selected_question:
                    selected_concept = concept_by_id[next(iter(selected_concept_ids))]
                    question_chunk_ids = source_ids(selected_question) or source_ids(selected_concept)
                    chunk_ids.update(question_chunk_ids)
                    for question_row in linked_questions:
                        if question_row["id"] == record_id:
                            question_row["sourceChunkIds"] = sorted(question_chunk_ids)

                source_rows = [c for c in snapshot_chunks if c.id in chunk_ids] if view else list(
                    db.scalars(
                        select(Chunk)
                        .where(Chunk.document_id == doc.id, Chunk.id.in_(chunk_ids))
                        .order_by(Chunk.ordinal)
                    )
                ) if chunk_ids else []
                source_embeddings = snapshot_embeddings if view else {
                    row.chunk_id: row
                    for row in db.scalars(
                        select(ChunkEmbedding).where(
                            ChunkEmbedding.document_id == doc.id,
                            ChunkEmbedding.chunk_id.in_([chunk.id for chunk in source_rows]),
                        )
                    )
                } if source_rows else {}
                relationship = {
                    "selected": {"kind": kind, "id": record_id, "title": selected_title},
                    "pageContent": page_content,
                    "sourceChunks": [
                        {
                            "id": chunk.id,
                            "page": chunk.page,
                            "ordinal": chunk.ordinal,
                            "text": chunk.text,
                            "embedded": chunk.id in source_embeddings,
                        }
                        for chunk in source_rows
                    ],
                    "concepts": [
                        {
                            "id": concept.get("id", ""),
                            "title": concept.get("title", "Untitled concept"),
                            "summary": concept.get("summary", ""),
                            "sourceChunkIds": sorted(source_ids(concept)),
                        }
                        for concept in linked_concepts
                    ],
                    "lessons": linked_lessons,
                    "questions": linked_questions,
                }

            return {
                "document": {
                    "id": doc.id,
                    "filename": view["filename"] if view else doc.filename,
                    "status": doc_status,
                    "pages": view["pages"] if view else doc.pages,
                    "missingTextPages": missing_text_pages,
                    "analysisComplete": graph.get("analysis", {}).get("complete", False),
                    "coverage": graph.get("coverage"),
                },
                "counts": counts,
                "savedCounts": saved_counts,
                "sourceWarningCount": source_warning_count,
                "runId": run_id,
                "inspectionMode": inspection_mode,
                "inspectionScope": "changes" if baseline is not None else "saved",
                "kind": kind,
                "offset": offset,
                "limit": limit,
                "total": counts[kind],
                "items": items,
                "relationship": relationship,
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
