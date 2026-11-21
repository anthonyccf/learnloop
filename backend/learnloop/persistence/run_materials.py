from sqlalchemy import select

from learnloop.persistence.database import Document, Run, RunMaterial


def documents_for(db, run_id, course_id):
    inputs = db.get(Run, run_id).input
    if inputs.get("run_scoped"):
        return select(RunMaterial).where(
            RunMaterial.run_id == run_id, RunMaterial.id == inputs["document_id"]
        )
    return (
        select(Document)
        .where(Document.course_id == course_id, Document.status.in_(("prepared", "published")))
        .order_by(Document.id)
    )


def document_for(db, run_id, document_id, lock=False):
    if db.get(Run, run_id).input.get("run_scoped"):
        return db.get(RunMaterial, (run_id, document_id), with_for_update=lock)
    return db.get(Document, document_id, with_for_update=lock)
