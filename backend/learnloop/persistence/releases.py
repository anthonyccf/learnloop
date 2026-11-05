"""Atomic, validated publication. Mutable preparation never supplies released content."""

import copy
import hashlib
import json
import re
from types import SimpleNamespace

from sqlalchemy import event, select

from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Chunk, Course, CourseRelease, Document

PREPARED_STATUSES = ("prepared", "published")


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def scope_fingerprint(lesson, curriculum):
    return fingerprint({"lesson": lesson, "curriculum": curriculum})


@event.listens_for(CourseRelease, "before_update")
@event.listens_for(CourseRelease, "before_delete")
def immutable_release(mapper, connection, target):
    raise ValueError("Course releases are immutable; publish a new version")


def get_release(db, course_id, release_id=None):
    query = select(CourseRelease).where(CourseRelease.course_id == course_id)
    query = (
        query.where(CourseRelease.id == release_id)
        if release_id
        else query.order_by(CourseRelease.version.desc()).limit(1)
    )
    release = db.scalar(query)
    if release_id and not release:
        raise ServiceError("invalid_release", "The pinned course release is unavailable.", False)
    if release and fingerprint(release.payload) != release.sha256:
        raise ServiceError(
            "invalid_release", "The course release failed its integrity check.", False
        )
    return release


def released_documents(db, course_id, release_id=None):
    release = get_release(db, course_id, release_id)
    return (
        [SimpleNamespace(**copy.deepcopy(d)) for d in release.payload["documents"]]
        if release
        else []
    )


def released_chunks(db, course_id, release_id=None):
    release = get_release(db, course_id, release_id)
    return copy.deepcopy(release.payload["chunks"]) if release else {}


def pin_session(db, session):
    # Course -> session lock order matches assignment, submission and publication.
    db.scalar(select(Course).where(Course.id == session.course_id).with_for_update())
    db.refresh(session, with_for_update=True)
    if session.release_id is None:
        release = get_release(db, session.course_id)
        if not release:
            raise ServiceError(
                "course_not_ready",
                "Prepare and publish complete course resources before studying.",
                False,
            )
        session.release_id = release.id
    return session.release_id


def publish_course(db, course_id, run_id=None):
    """Validate under the course lock, then append a complete snapshot in this transaction."""
    from learnloop.agents.expert.curriculum import validate_curriculum
    from learnloop.agents.expert.materials import (
        MATERIALS_VERSION,
        difficulty_complete,
        material_valid,
    )
    from learnloop.agents.expert.organization import current_organization, validate_organization
    from learnloop.core.domain import validate_graph
    from learnloop.core.grounding import grounding_valid, validate_sources
    from learnloop.core.schemas import Lesson, Question
    from learnloop.persistence.repository import compose_graph

    db.scalar(select(Course).where(Course.id == course_id).with_for_update())
    # Lock every included document: a material checkpoint cannot change during publication.
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.course_id == course_id)
            .order_by(Document.id)
            .with_for_update()
        )
    )
    if not documents or any(d.status not in PREPARED_STATUSES for d in documents):
        raise ServiceError(
            "course_not_ready",
            "All uploaded documents must finish preparation before publication.",
            False,
        )
    concepts = [c for d in documents for c in d.graph.get("concepts", [])]
    if not concepts or len({c["id"] for c in concepts}) != len(concepts):
        raise ServiceError(
            "course_not_ready", "A complete, distinct concept catalog is required.", False
        )
    chunks = {
        c.id: {
            "id": c.id,
            "document_id": c.document_id,
            "course_id": course_id,
            "page": c.page,
            "text": c.text,
            "label": next(d.filename for d in documents if d.id == c.document_id),
        }
        for c in db.scalars(
            select(Chunk).where(Chunk.course_id == course_id).order_by(Chunk.id).with_for_update()
        )
    }
    organization = current_organization(documents, concepts)
    if not organization or not organization.get("coverage", {}).get("reviewed"):
        raise ServiceError(
            "course_not_ready", "A current reviewed course organization is required.", False
        )
    validate_organization(concepts, organization["topics"], organization, set(chunks))
    if organization["prerequisites"]:
        validate_sources({"prerequisites": organization["prerequisites"]}, chunks)
    graph = compose_graph(documents)
    validate_graph(graph)
    validate_sources({"concepts": concepts}, chunks)
    assignments = []
    for doc in documents:
        draft = doc.graph
        if not draft.get("analysis", {}).get("complete") or draft.get("sourceIssues"):
            raise ServiceError(
                "course_not_ready", "Source analysis or resource review is incomplete.", False
            )
        analysis = draft["analysis"]
        sections = analysis.get("sections", {})
        coverage = draft.get("coverage", {})
        if (
            not sections
            or len(sections) != coverage.get("totalSections")
            or coverage.get("processedPassages")
            != sum(c["document_id"] == doc.id for c in chunks.values())
        ):
            raise ServiceError(
                "course_not_ready", "Source analysis coverage is incomplete or stale.", False
            )
        for key, section in sections.items():
            reviewed = {k: v for k, v in section.items() if k != "mapping"}
            if section.get("concepts") and not grounding_valid(
                reviewed, chunks, analysis.get("grounding", {}).get(key)
            ):
                raise ServiceError(
                    "course_not_ready",
                    "A concept source-review receipt is missing or stale.",
                    False,
                )
        curriculum = draft.get("curriculum", {})
        if curriculum.get("signature") != organization["signature"]:
            raise ServiceError("course_not_ready", "Curriculum is missing or stale.", False)
        objectives = curriculum.get("objectives", {})
        if set(objectives) != {c["id"] for c in draft.get("concepts", [])}:
            raise ServiceError("course_not_ready", "Curriculum coverage is incomplete.", False)
        assignments.extend(objectives.values())
        for concept in draft.get("concepts", []):
            pack = draft.get("resources", {}).get(concept["id"], {})
            if (
                pack.get("version") != MATERIALS_VERSION
                or not difficulty_complete(pack)
                or not material_valid(pack, chunks)
            ):
                raise ServiceError(
                    "course_not_ready",
                    f"Lessons and all three quiz levels must pass source review: {concept['id']}",
                    False,
                )
            Lesson.model_validate(pack["lesson"])
            for lesson in pack.get("lessonsByDifficulty", {}).values():
                Lesson.model_validate(lesson)
            questions = [Question.model_validate(q) for q in pack["tests"]]
            if any(not q.rubric or not q.referenceAnswer for q in questions):
                raise ServiceError(
                    "course_not_ready", "Private reference answers and rubrics are required.", False
                )
            prompts = [re.sub(r"\W+", "", q.prompt.casefold()) for q in questions]
            if len(prompts) != len(set(prompts)):
                raise ServiceError(
                    "course_not_ready", "Duplicate quiz prompts must be repaired.", False
                )
            if not pack.get("scopeReview", {}).get("accepted") or pack.get(
                "scopeFingerprint"
            ) != scope_fingerprint(pack["lesson"], objectives[concept["id"]]):
                raise ServiceError(
                    "course_not_ready", "Lesson scope review is missing or stale.", False
                )
    validate_curriculum({"objectives": assignments}, concepts, graph["prerequisites"])
    payload = {
        "format": 1,
        "graph": graph,
        "documents": [
            {
                "id": d.id,
                "course_id": d.course_id,
                "filename": d.filename,
                "sha256": d.sha256,
                "pages": d.pages,
                "status": "published",
                "graph": copy.deepcopy(d.graph),
            }
            for d in documents
        ],
        "chunks": chunks,
    }
    latest = get_release(db, course_id)
    for doc in documents:
        doc.status = "published"
    # Ignore ancestry when checking an idempotent retry of the latest content.
    if latest and {k: v for k, v in latest.payload.items() if k != "previousReleaseId"} == payload:
        return latest
    # A rebuild may return to an earlier snapshot: preserve monotonic release versions.
    # Bind the preceding release so identical content can still be republished immutably.
    payload["previousReleaseId"] = latest.id if latest else None
    release = CourseRelease(
        course_id=course_id,
        version=latest.version + 1 if latest else 1,
        sha256=fingerprint(payload),
        payload=payload,
        run_id=run_id,
    )
    db.add(release)
    db.flush()
    return release
