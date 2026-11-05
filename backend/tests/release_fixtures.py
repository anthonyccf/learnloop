"""Seed synthetic historical catalogs for legacy-policy tests, bypassing publication on purpose.

These temporary-database fixtures exercise invalid legacy inputs and fallback guards.
Release publication itself must be tested through publish_course, never this helper.
"""

import copy

from sqlalchemy import select

from learnloop.persistence.database import Chunk, CourseRelease, Document
from learnloop.persistence.releases import fingerprint, get_release
from learnloop.persistence.repository import compose_graph


def seed_legacy_release(db, course_id):
    db.flush()
    docs = list(
        db.scalars(select(Document).where(Document.course_id == course_id).order_by(Document.id))
    )
    latest = get_release(db, course_id)
    payload = {
        "format": "synthetic-test-fixture",
        "graph": compose_graph(docs),
        "documents": [
            {
                "id": d.id,
                "course_id": course_id,
                "filename": d.filename,
                "sha256": d.sha256,
                "pages": d.pages,
                "status": d.status,
                "graph": copy.deepcopy(d.graph),
            }
            for d in docs
        ],
        "chunks": {
            c.id: {
                "id": c.id,
                "document_id": c.document_id,
                "course_id": course_id,
                "page": c.page,
                "text": c.text,
                "label": next(d.filename for d in docs if d.id == c.document_id),
            }
            for c in db.scalars(select(Chunk).where(Chunk.course_id == course_id))
        },
    }
    release = CourseRelease(
        course_id=course_id,
        version=latest.version + 1 if latest else 1,
        sha256=fingerprint(payload),
        payload=payload,
    )
    db.add(release)
    db.flush()
    return release
