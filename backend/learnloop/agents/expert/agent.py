"""Expert Agent entry point: extract, index, discover, organize, and prepare.

SQL checkpoints preserve completed work across worker retries. Model output is
checked by shared domain/runtime code before publication.
"""

from sqlalchemy import select

from learnloop.agents.expert.analysis import analyze_document
from learnloop.agents.expert.curriculum import prepare_curriculum
from learnloop.agents.expert.deduplication import deduplicate_course
from learnloop.agents.expert.materials import prepare_materials
from learnloop.agents.expert.organization import organize_course
from learnloop.core.domain import chunk_id, extract
from learnloop.persistence.database import Chunk, Document, Run
from learnloop.persistence.releases import publish_course
from learnloop.runtime.events import run_status, step


def prepare_graph(factory, services, run_id):
    settings = services.settings
    with factory.begin() as db:
        run = db.get(Run, run_id)
        doc = db.get(Document, run.input["document_id"])
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
        if not has_chunks or doc.status not in (
            "extracted",
            "indexed",
            "needs_review",
            "prepared",
            "published",
        ):
            pages, extracted = extract(
                doc.content, doc.filename, settings.max_pages, settings.max_chunks
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
            db.get(Document, document_id).status = "indexed"
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
        for document_id in document_ids:
            with factory.begin() as db:
                current_run = db.get(Run, run_id)
                current_run.input = {**current_run.input, "document_id": document_id}
            prepare_materials(factory, services, run_id, document_id, finalize=False)
        with factory.begin() as db:
            publish_course(db, db.get(Run, run_id).course_id, run_id)
            run_status(
                db,
                run_id,
                "completed",
                "The connected learning pyramid, lessons and tests are ready.",
            )
        return
    prepare_graph(factory, services, run_id)
    with factory() as db:
        document_id = db.get(Run, run_id).input["document_id"]
    deduplicate_course(factory, services, run_id, document_id)
    organize_course(factory, services, run_id, document_id)
    prepare_curriculum(factory, services, run_id, document_id)
    # A new upload may change scopes of existing lessons as well.
    with factory() as db:
        course_id = db.get(Document, document_id).course_id
        document_ids = list(
            db.scalars(
                select(Document.id).where(
                    Document.course_id == course_id, Document.status.in_(("prepared", "published"))
                )
            )
        )
    for document_id in document_ids:
        with factory.begin() as db:
            current_run = db.get(Run, run_id)
            current_run.input = {**current_run.input, "document_id": document_id}
        prepare_materials(factory, services, run_id, document_id, finalize=False)
    with factory.begin() as db:
        publish_course(db, course_id, run_id)
        run_status(
            db, run_id, "completed", "The connected learning pyramid, lessons and tests are ready."
        )
