"""Courses HTTP endpoints; registered by the application factory."""

import copy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from learnloop.agents.expert.materials import MATERIALS_VERSION, material_valid, public_materials
from learnloop.agents.expert.organization import current_organization
from learnloop.api.dependencies import ApiContext
from learnloop.core.schemas import ConceptTargetUpdate, CourseCreate, CourseRename, Search
from learnloop.persistence.database import (
    Chunk,
    Course,
    Document,
    LearnerState,
    Run,
)
from learnloop.persistence.releases import (
    get_release,
    publish_course,
    released_chunks,
    released_documents,
)
from learnloop.persistence.repository import course_graph, learner, public_state, retrieve
from learnloop.runtime.events import new_run


def release_summary(release):
    if not release:
        return None
    return {
        "id": release.id,
        "version": release.version,
        "sha256": release.sha256,
        "createdAt": release.created_at.isoformat(),
        "conceptCount": len(release.payload["graph"]["concepts"]),
    }


def build_router(context: ApiContext):
    router = APIRouter(tags=["Courses"])
    factory = context.factory
    lock_course = context.lock_course
    owned = context.owned
    owner = context.owner
    services = context.services

    @router.get("/api/courses/{course_id}/releases")
    def releases(course_id: str, principal=Depends(owner)):
        from learnloop.persistence.database import CourseRelease

        with factory() as db:
            owned(db, Course, course_id, principal)
            return {
                "releases": [
                    release_summary(r)
                    for r in db.scalars(
                        select(CourseRelease)
                        .where(CourseRelease.course_id == course_id)
                        .order_by(CourseRelease.version.desc())
                    )
                ]
            }

    @router.post("/api/courses/{course_id}/releases", status_code=201)
    def publish_prepared(course_id: str, principal=Depends(owner)):
        from learnloop.core.errors import ServiceError

        with factory.begin() as db:
            owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            try:
                release = publish_course(db, course_id)
            except (ServiceError, ValueError) as error:
                raise HTTPException(409, getattr(error, "message", str(error))) from error
            return release_summary(release)

    @router.post("/api/courses", status_code=201)
    def create_course(body: CourseCreate, principal=Depends(owner)):
        with factory.begin() as db:
            course = Course(title=body.title, owner_id=principal)
            db.add(course)
            db.flush()
            db.add(LearnerState(course_id=course.id, owner_id=principal))
            return {"id": course.id, "title": course.title}

    @router.post("/api/courses/{course_id}/rename")
    def rename_course(course_id: str, body: CourseRename, principal=Depends(owner)):
        with factory.begin() as db:
            course = owned(db, Course, course_id, principal)
            course.title = body.title
            return {"id": course.id, "title": course.title}

    @router.get("/api/courses")
    def list_courses(principal=Depends(owner)):
        with factory() as db:
            return [
                {"id": c.id, "title": c.title}
                for c in db.scalars(
                    select(Course).where(Course.owner_id == principal).order_by(Course.created_at)
                )
            ]

    @router.get("/api/courses/{course_id}")
    def get_course(course_id: str, principal=Depends(owner)):
        with factory() as db:
            course = owned(db, Course, course_id, principal)
            release = get_release(db, course_id)
            documents = list(db.scalars(select(Document).where(Document.course_id == course_id)))
            chunks = {}
            for chunk in db.scalars(select(Chunk).where(Chunk.course_id == course_id)):
                chunks.setdefault(chunk.document_id, {})[chunk.id] = {"text": chunk.text}
            reviewed = {
                doc.id: [
                    pack
                    for pack in doc.graph.get("resources", {}).values()
                    if material_valid(pack, chunks.get(doc.id, {}))
                ]
                for doc in documents
            }
            return {
                "id": course.id,
                "title": course.title,
                "graph": course_graph(db, course_id, release.id)
                if release
                else {"concepts": [], "prerequisites": [], "topics": [], "related": []},
                "release": release_summary(release),
                "documents": [
                    {
                        "id": d.id,
                        "filename": d.filename,
                        "status": d.status,
                        "pages": d.pages,
                        "coverage": d.graph.get("coverage"),
                        "lessonCount": len(reviewed[d.id]),
                        "postLessonCount": sum(
                            r.get("version") == MATERIALS_VERSION for r in reviewed[d.id]
                        ),
                        "testCount": sum(len(r.get("tests", [])) for r in reviewed[d.id]),
                    }
                    for d in documents
                ],
            }

    @router.post("/api/courses/{course_id}/organize", status_code=202)
    def organize(course_id: str, principal=Depends(owner)):
        with factory.begin() as db:
            course = owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            documents = list(
                db.scalars(
                    select(Document)
                    .where(
                        Document.course_id == course_id,
                        Document.status.in_(("prepared", "published")),
                    )
                    .order_by(Document.id)
                )
            )
            if not documents:
                raise HTTPException(409, "Publish course concepts before organizing the map.")
            for run in db.scalars(select(Run).where(Run.course_id == course_id)):
                if run.snapshot["workflow"] == "course_preparation" and run.snapshot["status"] in (
                    "queued",
                    "running",
                    "paused",
                ):
                    return {"runId": run.id, "status": run.snapshot["status"]}
            release = get_release(db, course_id)
            if (
                release
                and all(
                    any(
                        saved["id"] == doc.id and saved["graph"] == doc.graph
                        for saved in release.payload["documents"]
                    )
                    for doc in documents
                )
                and current_organization(
                    documents, [c for doc in documents for c in doc.graph.get("concepts", [])]
                )
            ):
                return {"status": "ready"}
            drafts = [
                r.input["organizationDraft"]
                for r in db.scalars(select(Run).where(Run.course_id == course_id))
                if r.input.get("organizationDraft")
            ]
            input = {"document_id": documents[0].id, "organize_only": True}
            if drafts:
                input["organizationDraft"] = max(drafts, key=len)
            run = new_run(db, course, "course_preparation", input)
            return {"runId": run.id, "status": "queued"}

    @router.get("/api/courses/{course_id}/materials")
    def learning_materials(course_id: str, releaseId: str | None = None, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            release = get_release(db, course_id, releaseId)
            releaseId = release.id if release else None
            documents = released_documents(db, course_id, releaseId) if release else []
            pages, chunks = {}, {}
            for chunk in (released_chunks(db, course_id, releaseId) if release else {}).values():
                pages.setdefault(chunk["document_id"], {})[chunk["id"]] = chunk["page"]
                chunks.setdefault(chunk["document_id"], {})[chunk["id"]] = {"text": chunk["text"]}
            # Use the same published teaching sequence as the map and tutor,
            # The complete graph and materials come from one immutable release.
            concepts = course_graph(db, course_id, releaseId)["concepts"] if release else []
            by_concept = {
                material["conceptId"]: material
                for doc in documents
                for material in public_materials(doc, pages.get(doc.id), chunks.get(doc.id))
            }
            return {
                "materials": [by_concept[c["id"]] for c in concepts if c["id"] in by_concept],
                "expectedCount": len(concepts),
            }

    @router.post("/api/courses/{course_id}/search")
    def search(course_id: str, body: Search, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            return {
                "passages": retrieve(db, services, course_id, principal, body.query, body.limit)
            }

    @router.get("/api/courses/{course_id}/learner-state")
    def get_state(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            return public_state(learner(db, course_id, principal), course_graph(db, course_id))

    @router.post("/api/courses/{course_id}/concepts/{concept_id}/target")
    def update_target(
        course_id: str, concept_id: str, body: ConceptTargetUpdate, principal=Depends(owner)
    ):
        with factory.begin() as db:
            owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            state = learner(db, course_id, principal, lock=True)
            if state.version != body.expectedLearnerVersion:
                raise HTTPException(
                    409, "Learner state changed. Refresh before changing the target."
                )
            graph = course_graph(db, course_id)
            selected = next((c for c in graph["concepts"] if c["id"] == concept_id), None)
            if not selected:
                raise HTTPException(404, "This concept is not published in the selected course.")
            layer = (selected.get("curriculum") or {}).get("layer")
            if layer in ("basic", "intermediate", "advanced"):
                if body.targetDifficulty != layer:
                    raise HTTPException(
                        409, "This concept's assessment target follows its curriculum layer."
                    )
                return {
                    "conceptId": concept_id,
                    "targetDifficulty": layer,
                    "learnerVersion": state.version,
                }
            if selected.get("targetDifficulty", "intermediate") != body.targetDifficulty:
                # Learner goals are independent from the immutable content release.
                from learnloop.persistence.plans import get_plan, record_revision

                plan = get_plan(db, course_id, principal, create=True)
                data = copy.deepcopy(plan.data)
                data.setdefault("targetDifficulties", {})[concept_id] = body.targetDifficulty
                record_revision(
                    db,
                    plan,
                    f"target:{concept_id}:{state.version}",
                    {"conceptId": concept_id, "targetDifficulty": body.targetDifficulty},
                    plan.goal,
                    data,
                )
                state.version += 1
            return {
                "conceptId": concept_id,
                "targetDifficulty": body.targetDifficulty,
                "learnerVersion": state.version,
            }

    return router
