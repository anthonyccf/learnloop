"""Courses HTTP endpoints; registered by the application factory."""

import copy

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import load_only

from learnloop.agents.expert.materials import MATERIALS_VERSION, material_valid, public_materials
from learnloop.agents.expert.organization import current_organization
from learnloop.api.dependencies import ApiContext
from learnloop.core.schemas import (
    ConceptTargetUpdate,
    CourseCreate,
    CourseRename,
    ExpertPromptTemplate,
    Search,
    StrictModel,
    TopicGroup,
)
from learnloop.persistence.database import (
    Chunk,
    Course,
    Document,
    LearnerState,
    Run,
    RunHierarchy,
    RunMaterial,
)
from learnloop.persistence.learner_memory import learner_memory
from learnloop.persistence.releases import (
    current_material_release,
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


class HierarchyUpdate(StrictModel):
    expectedReleaseId: str
    topics: list[TopicGroup]


class HierarchyPurge(StrictModel):
    expectedReleaseId: str


class HierarchyRunRequest(StrictModel):
    documentIds: list[str]
    parentRunId: str | None = None
    reanalyze: bool = False
    promptTemplate: ExpertPromptTemplate | None = None


def hierarchy_source(db, course_id, run_id):
    from learnloop.persistence.database import CourseRelease

    run = db.get(Run, run_id)
    if run is None or run.course_id != course_id:
        raise HTTPException(404, "Hierarchy run not found.")
    result = db.get(RunHierarchy, run_id)
    if result:
        return {"graph": result.graph, "documents": result.documents, "ready": result.ready}
    release = db.scalar(
        select(CourseRelease)
        .where(CourseRelease.course_id == course_id, CourseRelease.run_id == run_id)
        .order_by(CourseRelease.version.desc())
    )
    if release and release.payload["graph"].get("topics"):
        return release.payload
    raise HTTPException(409, "This run has no saved hierarchy yet.")

def queue_hierarchy(db, course, document_ids, *, parent_run_id=None, reanalyze=False, prompt_template=None):
    """Queue one Expert generation while the caller holds the course lock."""
    from learnloop.agents.expert.run_hierarchy import prune_topics

    course_id = course.id
    ids = list(dict.fromkeys(document_ids))
    if not ids:
        raise HTTPException(422, "Choose at least one material.")
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.course_id == course_id, Document.id.in_(ids))
            .options(
                load_only(
                    Document.id,
                    Document.sha256,
                    Document.pages,
                    Document.filename,
                    Document.status,
                )
            )
        )
    )
    if len(docs) != len(ids):
        raise HTTPException(422, "Choose materials from this course.")
    active = db.execute(
        select(
            Run.input["_inspection_document_ids"], Run.input["document_id"].as_string()
        ).where(
            Run.course_id == course_id,
            Run.snapshot["workflow"].as_string() == "course_preparation",
            Run.snapshot["status"].as_string().in_(("queued", "paused", "running")),
        )
    )
    if any(set(ids).intersection(selected or [primary]) for selected, primary in active):
        raise HTTPException(409, "A selected material already has an active run.")
    parent = hierarchy_source(db, course_id, parent_run_id) if parent_run_id else {}
    copies = {d["id"]: d for d in parent.get("documents", [])}
    delta = [key for key in ids if key not in copies or reanalyze]
    for key in delta:
        copies.pop(key, None)
    if reanalyze:
        replaced_chunks = set(
            db.scalars(select(Chunk.id).where(Chunk.document_id.in_(delta)))
        )
        for saved in copies.values():
            for concept in saved["graph"].get("concepts", []):
                concept["sources"] = [
                    ref
                    for ref in concept["sources"]
                    if ref["chunkId"] not in replaced_chunks
                ]
                concept["sourceChunkIds"] = sorted(
                    set(concept.get("sourceChunkIds", [])) - replaced_chunks
                )
    retained_concepts = [c for d in copies.values() for c in d["graph"].get("concepts", [])]
    retained = {c["id"] for c in retained_concepts}
    graph = parent.get("graph", {})
    base = {
        "concepts": retained_concepts,
        "topics": prune_topics(graph.get("topics", []), retained),
        "related": [
            e for e in graph.get("related", []) if {e["first"], e["second"]} <= retained
        ],
        "prerequisites": [
            e
            for e in graph.get("prerequisites", [])
            if {e["prerequisite"], e["dependent"]} <= retained
        ],
    }
    run = new_run(
        db,
        course,
        "course_preparation",
        {
            "run_scoped": True,
            "document_id": ids[0],
            "selected_document_ids": delta,
            "requested_document_ids": ids,
            "hierarchy_mode": "continue" if parent else "new",
            "parent_run_id": parent_run_id,
            "base_graph": base,
            "review_all_sections": True,
            "prompt_template": prompt_template,
        },
    )
    run.input = {
        **run.input,
        "_inspection_document_ids": ids,
        "prompt_template_fingerprint": run.id,
    }
    for d in copies.values():
        db.add(
            RunMaterial(
                run_id=run.id,
                course_id=course_id,
                **{
                    k: copy.deepcopy(d[k])
                    for k in ("id", "filename", "sha256", "pages", "graph", "status")
                },
            )
        )
    for d in docs:
        if d.id in delta:
            db.add(
                RunMaterial(
                    run_id=run.id,
                    course_id=course_id,
                    id=d.id,
                    filename=d.filename,
                    sha256=d.sha256,
                    pages=d.pages,
                    graph={},
                    status=d.status,
                )
            )
    return run


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

    @router.get("/api/courses/{course_id}/hierarchy-sources")
    def hierarchy_sources(course_id: str, principal=Depends(owner)):
        from learnloop.persistence.database import CourseRelease

        with factory() as db:
            owned(db, Course, course_id, principal)
            releases = db.scalars(
                select(CourseRelease)
                .where(CourseRelease.course_id == course_id, CourseRelease.run_id.is_not(None))
                .order_by(CourseRelease.version.desc())
            )
            return [
                {
                    "releaseId": release.id,
                    "runId": release.run_id,
                    "version": release.version,
                    "createdAt": release.created_at.isoformat(),
                    "topics": release.payload.get("graph", {}).get("topics", []),
                    "concepts": release.payload.get("graph", {}).get("concepts", []),
                }
                for release in releases
                if release.payload.get("graph", {}).get("topics")
            ]

    @router.get("/api/courses/{course_id}/hierarchy-runs")
    def saved_hierarchies(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            from learnloop.persistence.database import CourseRelease

            legacy = dict(
                db.execute(
                    select(CourseRelease.run_id, CourseRelease.id)
                    .where(CourseRelease.course_id == course_id, CourseRelease.run_id.is_not(None))
                    .order_by(CourseRelease.version)
                ).all()
            )
            query = select(
                Run.id,
                Run.input["_started_at"].as_string(),
                Run.input["hierarchy_filenames"],
                Run.input["hierarchy_revision"].as_integer(),
                Run.input["hierarchy_ready"].as_boolean(),
                Run.input["published_release_id"].as_string(),
                Run.snapshot["status"].as_string(),
                RunHierarchy.documents,
            ).outerjoin(
                RunHierarchy, RunHierarchy.run_id == Run.id
            ).where(
                Run.course_id == course_id,
                Run.owner_id == principal,
                Run.snapshot["workflow"].as_string() == "course_preparation",
            )
            items = []
            for run_id, created, filenames, revision, ready, published, status, documents in db.execute(query):
                if revision or run_id in legacy:
                    release_id = published or legacy.get(run_id)
                    items.append(
                        {
                            "runId": run_id,
                            "createdAt": created or "",
                            "filenames": filenames or [],
                            "documents": [
                                {"id": document["id"], "filename": document["filename"]}
                                for document in (documents or [])
                            ],
                            "revision": revision or 0,
                            "ready": bool(ready and status == "completed"),
                            "releaseId": release_id,
                            "published": bool(release_id),
                        }
                    )
            return sorted(items, key=lambda i: i["createdAt"], reverse=True)

    @router.get("/api/courses/{course_id}/hierarchy-runs/{run_id}")
    def view_hierarchy(course_id: str, run_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            graph = db.scalar(
                select(RunHierarchy.graph)
                .join(Run)
                .where(RunHierarchy.run_id == run_id, Run.course_id == course_id)
            )
            return graph if graph is not None else hierarchy_source(db, course_id, run_id)["graph"]

    @router.post("/api/courses/{course_id}/hierarchy-runs", status_code=202)
    def start_hierarchy(course_id: str, body: HierarchyRunRequest, principal=Depends(owner)):
        with factory.begin() as db:
            course = owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            run = queue_hierarchy(
                db, course, body.documentIds,
                parent_run_id=body.parentRunId, reanalyze=body.reanalyze,
                prompt_template=body.promptTemplate.model_dump() if body.promptTemplate else None,
            )
            return {"runId": run.id, "status": "queued"}

    @router.post("/api/courses/{course_id}/hierarchy-runs/{run_id}/publish")
    def publish_hierarchy(course_id: str, run_id: str, principal=Depends(owner)):
        from learnloop.core.errors import ServiceError

        with factory.begin() as db:
            owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            run = owned(db, Run, run_id, principal)
            result = db.get(RunHierarchy, run.id)
            if (
                run.course_id != course_id
                or run.snapshot["status"] != "completed"
                or not result
                or not result.ready
            ):
                raise HTTPException(409, "Finish preparation before publishing this run.")
            if release_id := run.input.get("published_release_id"):
                return release_summary(get_release(db, course_id, release_id))
            from learnloop.persistence.releases import publish_run_hierarchy

            try:
                release = publish_run_hierarchy(db, run_id)
            except (ServiceError, ValueError) as exc:
                raise HTTPException(409, getattr(exc, "message", str(exc))) from exc
            return release_summary(release)

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
            release = current_material_release(db, course_id) or get_release(db, course_id)
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
                "publishedMaterials": [
                    {"id": d["id"], "filename": d["filename"]}
                    for d in release.payload["documents"]
                ] if release else [],
                "documents": [
                    {
                        "id": d.id,
                        "filename": d.filename,
                        "status": d.status,
                        "pages": d.pages,
                        "coverage": d.graph.get("coverage"),
                        "sourceWarnings": [{"conceptId": key, **issue} for key, issue in d.graph.get("sourceIssues", {}).items()],
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
                and (organization := current_organization(
                    documents, [c for doc in documents for c in doc.graph.get("concepts", [])]
                )) and not organization.get("hierarchyPurged")
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

    @router.post("/api/courses/{course_id}/hierarchy")
    def update_hierarchy(course_id: str, body: HierarchyUpdate, principal=Depends(owner)):
        from learnloop.agents.expert.organization import validate_topics
        from learnloop.core.errors import ServiceError

        with factory.begin() as db:
            owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            release = current_material_release(db, course_id) or get_release(db, course_id)
            if not release or release.id != body.expectedReleaseId:
                raise HTTPException(409, "The published course changed. Refresh before saving the hierarchy.")
            if any(run.snapshot["workflow"] == "course_preparation" and run.snapshot["status"] in ("queued", "running", "paused") for run in db.scalars(select(Run).where(Run.course_id == course_id))):
                raise HTTPException(409, "Wait for course preparation to finish before saving the hierarchy.")
            documents = list(db.scalars(select(Document).where(Document.course_id == course_id).with_for_update()))
            published = {doc["id"]: doc for doc in release.payload["documents"]}
            if len(documents) != len(published) or any(doc.id not in published or doc.graph != published[doc.id]["graph"] for doc in documents):
                raise HTTPException(409, "Course preparation has changed. Publish it before editing the hierarchy.")
            concepts = [concept for doc in documents for concept in doc.graph.get("concepts", [])]
            organization = current_organization(documents, concepts)
            if not organization:
                raise HTTPException(409, "The course organization is unavailable or stale.")
            topics = [topic.model_dump() for topic in body.topics]
            try:
                validate_topics(concepts, topics)
                anchor = next(doc for doc in documents if doc.graph.get("organization") == organization)
                graph = copy.deepcopy(anchor.graph)
                graph["organization"]["topics"] = topics
                graph["organization"].pop("hierarchyPurged", None)
                graph["organization"]["coverage"]["topicCount"] = len(topics)
                graph["organization"]["coverage"]["groupedConceptCount"] = len(concepts)
                anchor.graph = graph
                db.flush()
                updated = publish_course(db, course_id)
            except (ServiceError, ValueError) as error:
                raise HTTPException(409, getattr(error, "message", str(error))) from error
            return release_summary(updated)

    @router.post("/api/courses/{course_id}/hierarchy/purge")
    def purge_hierarchy(course_id: str, body: HierarchyPurge, principal=Depends(owner)):
        from learnloop.core.errors import ServiceError

        with factory.begin() as db:
            owned(db, Course, course_id, principal)
            lock_course(db, course_id)
            release = current_material_release(db, course_id) or get_release(db, course_id)
            if not release or release.id != body.expectedReleaseId:
                raise HTTPException(409, "The published course changed. Refresh before purging the hierarchy.")
            if any(run.snapshot["workflow"] == "course_preparation" and run.snapshot["status"] in ("queued", "running", "paused") for run in db.scalars(select(Run).where(Run.course_id == course_id))):
                raise HTTPException(409, "Wait for course preparation to finish before purging the hierarchy.")
            documents = list(db.scalars(select(Document).where(Document.course_id == course_id).with_for_update()))
            published = {doc["id"]: doc for doc in release.payload["documents"]}
            if len(documents) != len(published) or any(doc.id not in published or doc.graph != published[doc.id]["graph"] for doc in documents):
                raise HTTPException(409, "Course preparation has changed. Publish it before purging the hierarchy.")
            concepts = [concept for doc in documents for concept in doc.graph.get("concepts", [])]
            organization = current_organization(documents, concepts)
            if not organization or not organization.get("topics"):
                raise HTTPException(409, "There is no current topic hierarchy to purge.")
            anchor = next(doc for doc in documents if doc.graph.get("organization") == organization)
            graph = copy.deepcopy(anchor.graph)
            graph["organization"]["topics"] = []
            graph["organization"]["hierarchyPurged"] = True
            graph["organization"]["coverage"].update(topicCount=0, groupedConceptCount=0)
            anchor.graph = graph
            db.flush()
            try:
                updated = publish_course(db, course_id)
            except (ServiceError, ValueError) as error:
                raise HTTPException(409, getattr(error, "message", str(error))) from error
            return release_summary(updated)

    @router.get("/api/courses/{course_id}/materials")
    def learning_materials(course_id: str, releaseId: str | None = None, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            release = (
                get_release(db, course_id, releaseId)
                if releaseId
                else current_material_release(db, course_id) or get_release(db, course_id)
            )
            releaseId = release.id if release else None
            documents = released_documents(db, course_id, releaseId) if release else []
            pages, chunks = {}, {}
            for chunk in (released_chunks(db, course_id, releaseId, extracted_only=True) if release else {}).values():
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
            release = current_material_release(db, course_id) or get_release(db, course_id)
            return {
                "passages": retrieve(
                    db, services, course_id, principal, body.query, body.limit,
                    release_id=release.id if release else None,
                )
            }

    @router.get("/api/courses/{course_id}/learner-state")
    def get_state(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            release = current_material_release(db, course_id) or get_release(db, course_id)
            return public_state(
                learner(db, course_id, principal),
                course_graph(db, course_id, release.id if release else None),
            )

    @router.get("/api/courses/{course_id}/learner-memory")
    def export_memory(course_id: str, principal=Depends(owner)):
        with factory() as db:
            owned(db, Course, course_id, principal)
            release = current_material_release(db, course_id) or get_release(db, course_id)
            release_id = release.id if release else None
            state = learner(db, course_id, principal)
            graph = course_graph(db, course_id, release_id)
            return JSONResponse(
                {"courseId": course_id, "releaseId": release_id,
                 "objectives": learner_memory(db, state, release_id, graph["concepts"])},
                headers={
                    "Content-Disposition": 'attachment; filename="learner-memory.json"',
                    "Cache-Control": "no-store",
                },
            )

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
