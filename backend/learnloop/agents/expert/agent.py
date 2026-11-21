"""Expert Agent entry point: extract, index, discover, organize, and prepare.

SQL checkpoints preserve completed work across worker retries. Model output is
checked by shared domain/runtime code before publication.
"""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import load_only

from learnloop.agents.expert.analysis import analyze_document
from learnloop.agents.expert.curriculum import prepare_curriculum
from learnloop.agents.expert.deduplication import deduplicate_course
from learnloop.agents.expert.materials import flagged_summary, prepare_materials
from learnloop.agents.expert.organization import organize_course
from learnloop.core.domain import chunk_id, extract
from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Chunk, Document, Run
from learnloop.persistence.releases import publish_course
from learnloop.persistence.run_materials import document_for
from learnloop.runtime.cancellation import RunStopped
from learnloop.runtime.events import run_status, step


def prepare_graph(factory, services, run_id):
    settings = services.settings
    with factory.begin() as db:
        run = db.get(Run, run_id)
        doc = document_for(db, run_id, run.input["document_id"])
        if doc.graph.get("analysis", {}).get("complete") and not run.input.get(
            "review_all_sections"
        ):
            doc.status = "prepared"
            run_status(
                db,
                run_id,
                "running",
                "Course concepts are staged. Preparing learning materials and tests before publication.",
            )
            return
        run_status(db, run_id, "running", "Expert preparation has started.")
        if doc.status == "published":
            doc.status = "prepared"
        step(
            db,
            run_id,
            "expert",
            "Extract source passages",
            "Read the uploaded document and preserve page locations.",
            "retrieve_evidence",
        )
        document_id, owner_id = doc.id, run.owner_id
        has_chunks = (
            db.scalar(select(Chunk.id).where(Chunk.document_id == doc.id).limit(1)) is not None
        )
        if not has_chunks:
            pages, extracted = extract(
                db.get(Document, document_id).content, doc.filename, settings.max_pages, settings.max_chunks
            )
            for ordinal, passage in enumerate(extracted):
                db.add(
                    Chunk(
                        id=chunk_id(doc.id, ordinal),
                        document_id=doc.id,
                        course_id=doc.course_id,
                        ordinal=ordinal,
                        **passage,
                    )
                )
            doc.pages, doc.status = pages, "extracted"
        db.flush()
        if run.input.get("run_scoped"):
            source = db.get(Document, document_id, options=[load_only(Document.pages, Document.status)])
            source.pages = doc.pages
        chunks = [
            {
                "id": c.id,
                "document_id": c.document_id,
                "course_id": c.course_id,
                "page": c.page,
                "text": c.text,
                "label": doc.filename,
            }
            for c in db.scalars(
                select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.ordinal)
            )
        ]
        indexed = doc.status in ("indexed", "needs_review", "prepared", "published")
    if not indexed:
        services.index(chunks, owner_id)
        with factory.begin() as db:
            document_for(db, run_id, document_id).status = "indexed"
            source = db.get(Document, document_id, options=[load_only(Document.pages, Document.status)])
            if source.status in ("uploaded", "queued", "extracted"):
                source.status = "indexed"
            step(
                db,
                run_id,
                "expert",
                "Prepare grounded concepts",
                "Passages are indexed. Generate source-backed concepts and prerequisite relationships.",
                "retrieve_evidence",
            )
    analyze_document(factory, services, run_id, document_id, chunks)


def run(factory, services, run_id):
    with factory() as db:
        run_input = db.get(Run, run_id).input
    if run_input.get("run_scoped"):
        from learnloop.agents.expert.run_hierarchy import prepare_run
        return prepare_run(factory, services, run_id)
    if run_input.get("rebuild_course"):
        # Discover every document before planning a shared curriculum.
        document_ids = run_input["document_ids"]
        for document_id in document_ids:
            with factory.begin() as db:
                r = db.get(Run, run_id)
                r.input = {**r.input, "document_id": document_id}
            prepare_graph(factory, services, run_id)
        document_id = document_ids[0]
        deduplicate_course(factory, services, run_id, document_id)
        organize_course(factory, services, run_id, document_id)
        prepare_curriculum(factory, services, run_id, document_id)
        source_warnings = prepare_course_materials(factory, services, run_id, document_ids)
        with factory() as db:
            course_id = db.get(Run, run_id).course_id
        finish(factory, run_id, course_id, source_warnings)
        return
    prepare_graph(factory, services, run_id)
    with factory() as db:
        document_id = db.get(Run, run_id).input["document_id"]
    deduplicate_course(factory, services, run_id, document_id)
    organize_course(factory, services, run_id, document_id)
    prepare_curriculum(factory, services, run_id, document_id)
    with factory() as db:
        course_id = document_for(db, run_id, document_id).course_id
    source_warnings = prepare_course_materials(factory, services, run_id, [document_id])
    finish(factory, run_id, course_id, source_warnings)


def prepare_course_materials(factory, services, run_id, document_ids):
    """Every document's lessons share one pool, so no document waits on another's slowest lesson."""
    if not document_ids:
        return []
    with (
        ThreadPoolExecutor(max_workers=services.settings.expert_material_workers) as lessons,
        ThreadPoolExecutor(max_workers=len(document_ids)) as documents,
    ):
        futures = [
            documents.submit(
                prepare_materials, factory, services, run_id, document_id, False, lessons
            )
            for document_id in document_ids
        ]
        flagged, failures = [], []
        for future in futures:
            try:
                flagged.extend(future.result())
            except RunStopped:
                raise
            except Exception as exc:
                failures.append(exc)
    if failures:
        raise failures[0]
    return flagged


def finish(factory, run_id, course_id, flagged):
    with factory.begin() as db:
        if flagged:
            run_status(db, run_id, "needs_review", flagged_summary(len(flagged)))
            return
        try:
            with db.begin_nested():
                publish_course(db, course_id, run_id)
        except ServiceError as error:
            if error.code != "course_not_ready":
                raise
            run_status(
                db, run_id, "needs_review",
                "The selected material was prepared, but the updated course could not be published. "
                f"{error.message} Other materials may also need to be refreshed before publishing.",
            )
            return
        run_status(
            db, run_id, "completed", "The connected learning pyramid, lessons and tests are ready."
        )
