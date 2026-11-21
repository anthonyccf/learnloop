"""Incrementally build one immutable hierarchy result from pinned material inputs."""

import copy

from sqlalchemy import select

from learnloop.agents.expert.analysis import _merge_section
from learnloop.agents.expert.curriculum import prepare_curriculum
from learnloop.agents.expert.materials import flagged_summary, prepare_materials
from learnloop.agents.expert.organization import catalog_signature, organize_course, validate_topics
from learnloop.persistence.database import Run, RunHierarchy, RunMaterial
from learnloop.persistence.repository import compose_graph
from learnloop.runtime.events import run_status


def materials(db, run_id):
    return list(
        db.scalars(select(RunMaterial).where(RunMaterial.run_id == run_id).order_by(RunMaterial.id))
    )


def prune_topics(topics, ids):
    """Keep branches that still contain inherited concepts, including ancestors."""
    by_id = {t["id"]: t for t in topics}
    keep = set()
    for topic in topics:
        if ids.intersection(topic["conceptIds"]):
            key = topic["id"]
            while key in by_id and key not in keep:
                keep.add(key)
                key = by_id[key].get("parentId")
    return [
        {**t, "conceptIds": [i for i in t["conceptIds"] if i in ids]}
        for t in topics
        if t["id"] in keep
    ]


def merge_candidates(factory, services, run_id, doc_id, previous):
    """Store duplicate evidence on the inherited goal while retaining its identity."""
    with factory() as db:
        doc = db.get(RunMaterial, (run_id, doc_id))
        candidates = doc.graph.get("concepts", [])
    if not previous or not candidates:
        return
    catalog = copy.deepcopy(previous)
    # Use the same matching prompt as intra-document deduplication. New IDs stay
    # document-qualified; only matches against the frozen catalog are adopted.
    mapping = _merge_section(services, {"concepts": candidates}, catalog, doc_id)
    original = {c["id"] for c in previous}
    matches = {key: value for key, value in mapping.items() if value in original}
    if not matches:
        return
    with factory.begin() as db:
        for doc in materials(db, run_id):
            graph = copy.deepcopy(doc.graph)
            if doc.id == doc_id:
                graph["conceptAliases"] = matches
                graph["concepts"] = [c for c in candidates if c["id"] not in matches]
                graph["prerequisites"] = [
                    e
                    for e in graph.get("prerequisites", [])
                    if e["prerequisite"] not in matches and e["dependent"] not in matches
                ]
            else:
                for concept in graph.get("concepts", []):
                    for candidate in candidates:
                        if matches.get(candidate["id"]) == concept["id"]:
                            concept["sourceChunkIds"] = sorted(
                                set(concept.get("sourceChunkIds", []))
                                | set(candidate.get("sourceChunkIds", []))
                            )
                            evidence = {
                                s["chunkId"]: s
                                for s in concept.get("sources", []) + candidate.get("sources", [])
                            }
                            concept["sources"] = list(evidence.values())
            doc.graph = graph


def snapshot(db, run, topics, prerequisites, related, *, ready=False):
    docs = [d for d in materials(db, run.id) if d.graph.get("analysis", {}).get("complete")]
    concepts = [c for d in docs for c in d.graph.get("concepts", [])]
    validate_topics(concepts, topics)
    signature = catalog_signature(concepts)
    organization = {
        "version": 1,
        "signature": signature,
        "topics": topics,
        "prerequisites": prerequisites,
        "related": related,
        "coverage": {
            "reviewed": True,
            "topicCount": len(topics),
            "documentCount": len(docs),
            "conceptCount": len(concepts),
            "groupedConceptCount": len(concepts),
        },
    }
    for doc in docs:
        graph = dict(doc.graph)
        graph.pop("organization", None)
        if doc == docs[0]:
            graph["organization"] = organization
        graph["curriculum"] = {**graph.get("curriculum", {}), "signature": signature}
        doc.graph = graph
    graph = compose_graph(docs)
    frozen = [
        {
            key: copy.deepcopy(getattr(doc, key))
            for key in ("id", "filename", "pages", "sha256", "status", "graph")
        }
        for doc in docs
    ]
    db.merge(RunHierarchy(run_id=run.id, graph=graph, documents=frozen, ready=ready))
    run.input = {
        **run.input,
        "hierarchy_filenames": [doc.filename for doc in docs],
        "hierarchy_revision": run.input.get("hierarchy_revision", 0) + 1,
        "hierarchy_ready": ready,
    }
    return graph


def prepare_run(factory, services, run_id):
    from learnloop.agents.expert.agent import prepare_graph

    with factory() as db:
        inputs = db.get(Run, run_id).input
        saved = db.get(RunHierarchy, run_id)
        prior = saved.graph if saved else inputs.get("base_graph") or {}
    selected = inputs["selected_document_ids"]
    for doc_id in selected:
        if doc_id in inputs.get("analyzed_ids", []):
            continue
        with factory.begin() as db:
            run = db.get(Run, run_id)
            prior_ids = {c["id"] for c in prior.get("concepts", [])}
            base_topics = prune_topics(prior.get("topics", []), prior_ids)
            run.input = {**run.input, "document_id": doc_id, "base_topics": base_topics}
        prepare_graph(factory, services, run_id)
        merge_candidates(factory, services, run_id, doc_id, prior.get("concepts", []))
        with factory() as db:
            has_goals = bool(db.get(RunMaterial, (run_id, doc_id)).graph.get("concepts"))
        if has_goals:
            organize_course(factory, services, run_id, doc_id)
            prepare_curriculum(factory, services, run_id, doc_id)
        with factory.begin() as db:
            run = db.get(Run, run_id)
            delta = db.get(RunMaterial, (run_id, doc_id)).graph.get("organization", {})
            topics = {t["id"]: copy.deepcopy(t) for t in base_topics}
            for topic in delta.get("topics", []):
                if topic["id"] in topics:
                    topics[topic["id"]]["conceptIds"].extend(topic["conceptIds"])
                else:
                    topics[topic["id"]] = topic
            result = snapshot(
                db,
                run,
                list(topics.values()),
                prior.get("prerequisites", []) + delta.get("prerequisites", []),
                prior.get("related", []) + delta.get("related", []),
            )
            prior = result
            analyzed = [*run.input.get("analyzed_ids", []), doc_id]
            run.input = {
                **run.input,
                "analyzed_ids": analyzed,
                "base_graph": {},
                "organizationDraft": {},
                "curriculumDraft": {},
            }
    with factory.begin() as db:
        run = db.get(Run, run_id)
        if not db.get(RunHierarchy, run_id):
            snapshot(
                db,
                run,
                prior.get("topics", []),
                prior.get("prerequisites", []),
                prior.get("related", []),
            )
    flagged = []
    for doc_id in selected:
        with factory.begin() as db:
            run = db.get(Run, run_id)
            run.input = {**run.input, "document_id": doc_id}
        issues = prepare_materials(factory, services, run_id, doc_id, finalize=False)
        flagged.extend(issues)
        with factory.begin() as db:
            doc = db.get(RunMaterial, (run_id, doc_id))
            doc.graph = {**doc.graph, "lessonsReady": not issues}
    with factory.begin() as db:
        run = db.get(Run, run_id)
        ready = all(
            doc.graph.get("lessonsReady", doc.status == "published")
            for doc in materials(db, run_id)
        )
        snapshot(
            db,
            run,
            prior.get("topics", []),
            prior.get("prerequisites", []),
            prior.get("related", []),
            ready=ready,
        )
        run_status(
            db,
            run_id,
            "running" if ready else "needs_review",
            flagged_summary(len(flagged))
            if flagged
            else "Run hierarchy and materials saved."
            if ready
            else "Hierarchy saved. An inherited material still needs lesson preparation.",
        )
    if ready:
        from learnloop.core.errors import ServiceError
        from learnloop.persistence.releases import publish_run_hierarchy

        try:
            with factory.begin() as db:
                publish_run_hierarchy(db, run_id)
                run_status(db, run_id, "completed", "Run materials published to the course.")
        except (ServiceError, ValueError) as error:
            with factory.begin() as db:
                run_status(db, run_id, "needs_review", f"Run materials were saved, but publication failed. {getattr(error, 'message', str(error))}")
