"""Merge repeated goals across uploads before assigning curriculum scopes."""

import copy

from sqlalchemy import select

from learnloop.agents.expert.organization import catalog_signature
from learnloop.agents.expert.prompts import MERGE_PROMPT
from learnloop.core.domain import validate_graph
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import ConceptMatches
from learnloop.persistence.database import Course, Document
from learnloop.runtime.events import step


def deduplicate_course(factory, services, run_id, document_id):
    with factory() as db:
        course_id = db.get(Document, document_id).course_id
        docs = list(
            db.scalars(
                select(Document)
                .where(
                    Document.course_id == course_id, Document.status.in_(("prepared", "published"))
                )
                .order_by(Document.id)
            )
        )
        docs.sort(
            key=lambda d: (not bool(d.graph.get("curriculum") or d.graph.get("resources")), d.id)
        )
        concepts = [c for d in docs for c in d.graph.get("concepts", [])]
        signature = catalog_signature(concepts)
        if all(d.graph.get("deduplication") == signature for d in docs):
            return
    catalog, aliases = [], {}
    for doc in docs:
        candidates = doc.graph.get("concepts", [])
        if catalog and candidates:
            matches = services.generate(
                "Expert",
                MERGE_PROMPT
                + "\nThese are concepts from different uploaded documents in the SAME course. Merge only identical teaching objectives, never merely related goals. Keep foundations, applications and synthesis distinct.",
                {
                    "existing": [
                        {"id": c["id"], "title": c["title"], "summary": c["summary"]}
                        for c in catalog
                    ],
                    "candidates": candidates,
                },
                ConceptMatches,
            )
            candidate_ids, known = {c["id"] for c in candidates}, {c["id"] for c in catalog}
            for m in matches.matches:
                if m.candidateId not in candidate_ids or m.existingId not in known:
                    raise ServiceError(
                        "invalid_merge", "Course duplicate mapping must use supplied IDs.", True
                    )
                if m.candidateId in aliases and aliases[m.candidateId] != m.existingId:
                    raise ServiceError(
                        "invalid_merge", "A repeated goal must have one primary home.", True
                    )
                aliases[m.candidateId] = m.existingId
        catalog.extend(c for c in candidates if c["id"] not in aliases)
    edges, seen = [], set()
    for doc in docs:
        for e in doc.graph.get("prerequisites", []):
            p, c = (
                aliases.get(e["prerequisite"], e["prerequisite"]),
                aliases.get(e["dependent"], e["dependent"]),
            )
            if p != c and (p, c) not in seen:
                edges.append({**e, "prerequisite": p, "dependent": c})
                seen.add((p, c))
    validate_graph({"concepts": catalog, "prerequisites": edges})
    final_signature = catalog_signature(catalog)
    with factory.begin() as db:
        db.scalar(select(Course).where(Course.id == course_id).with_for_update())
        latest = list(
            db.scalars(
                select(Document).where(
                    Document.course_id == course_id, Document.status.in_(("prepared", "published"))
                )
            )
        )
        if catalog_signature([c for d in latest for c in d.graph.get("concepts", [])]) != signature:
            raise ServiceError("catalog_changed", "Course changed during duplicate review.", True)
        for doc in latest:
            graph = copy.deepcopy(doc.graph)
            graph["conceptAliases"] = {
                **graph.get("conceptAliases", {}),
                **{c["id"]: aliases[c["id"]] for c in graph["concepts"] if c["id"] in aliases},
            }
            graph["concepts"] = [c for c in graph["concepts"] if c["id"] not in aliases]
            own_ids = {c["id"] for c in graph["concepts"]}
            # Keep each dependency's citation in its original document so a
            # resumed source review can still resolve it through that document.
            local_edges, local_seen = [], set()
            for edge in graph.get("prerequisites", []):
                parent = aliases.get(edge["prerequisite"], edge["prerequisite"])
                child = aliases.get(edge["dependent"], edge["dependent"])
                if child in own_ids and parent != child and (parent, child) not in local_seen:
                    local_edges.append({**edge, "prerequisite": parent, "dependent": child})
                    local_seen.add((parent, child))
            graph["prerequisites"] = local_edges
            graph["deduplication"] = final_signature
            if graph.get("coverage"):
                graph["coverage"]["conceptCount"] = len(graph["concepts"])
                graph["coverage"]["mergedConceptCount"] = len(graph["conceptAliases"])
            for id in aliases:
                graph.get("resources", {}).pop(id, None)
            doc.graph = graph
        step(
            db,
            run_id,
            "expert",
            "Merge course-wide repeated goals",
            f"Assigned {len(aliases)} repeated goals to existing primary teaching homes across uploads.",
            "publish_resources",
        )
