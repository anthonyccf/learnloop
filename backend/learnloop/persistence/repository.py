from sqlalchemy import select

from learnloop.agents.expert.organization import current_organization
from learnloop.core.domain import concept_state, effective_state, target_difficulty
from learnloop.persistence.database import Activity, Course, LearnerState, LearningPlan


def grounding_chunks(db, course_id, owner_id, ids, release_id=None):
    """Resolve citations through SQL ownership and publication, never vector IDs alone."""
    from learnloop.persistence.releases import released_chunks

    if not db.scalar(select(Course.id).where(Course.id == course_id, Course.owner_id == owner_id)):
        return {}
    return {id: c for id, c in released_chunks(db, course_id, release_id).items() if id in ids}


def course_graph(db, course_id, release_id=None):
    import copy

    from learnloop.persistence.releases import get_release

    release = get_release(db, course_id, release_id)
    graph = (
        copy.deepcopy(release.payload["graph"])
        if release
        else {"concepts": [], "prerequisites": [], "topics": [], "related": []}
    )
    # Legacy targets are learner configuration, never a mutation of released content.
    plan = db.scalar(select(LearningPlan).where(LearningPlan.course_id == course_id))
    overrides = plan.data.get("targetDifficulties", {}) if plan else {}
    for concept in graph["concepts"]:
        if not concept.get("curriculum") and concept["id"] in overrides:
            concept["targetDifficulty"] = overrides[concept["id"]]
    return graph


def compose_graph(documents):
    concepts, edges = [], []
    for document in documents:
        graph = document.graph
        concepts.extend(graph.get("concepts", []))
        edges.extend(graph.get("prerequisites", []))
    organization = current_organization(documents, concepts)
    assignments = {
        id: item
        for d in documents
        for id, item in d.graph.get("curriculum", {}).get("objectives", {}).items()
    }
    concepts = [{**c, "curriculum": assignments.get(c["id"])} for c in concepts]
    # Resolve existing courses without rewriting their catalog or assessment history.
    concepts = [{**c, "targetDifficulty": target_difficulty(c)} for c in concepts]
    if organization:
        by_id = {c["id"]: c for c in concepts}
        return {
            "concepts": curriculum_order(
                [by_id[id] for topic in organization["topics"] for id in topic["conceptIds"]],
                organization["prerequisites"],
            ),
            "prerequisites": organization["prerequisites"],
            "topics": organization["topics"],
            "related": organization["related"],
            "organization": organization["coverage"],
        }
    return {"concepts": concepts, "prerequisites": edges, "topics": [], "related": []}


def learner(db, course_id, owner_id, lock=False):
    query = select(LearnerState).where(
        LearnerState.course_id == course_id, LearnerState.owner_id == owner_id
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def public_state(record, graph=None):
    return {
        "version": record.version,
        "overallStates": {
            c["id"]: concept_state(c, record.evidence) for c in (graph or {}).get("concepts", [])
        },
        "targetDifficulties": {
            c["id"]: target_difficulty(c) for c in (graph or {}).get("concepts", [])
        },
        "concepts": {
            concept: {
                difficulty: {**value, "state": effective_state(value)}
                for difficulty, value in levels.items()
            }
            for concept, levels in record.evidence.items()
        },
    }


def public_activity(activity: Activity | None):
    if not activity:
        return None
    # Deliberate allowlist: never serialize ORM objects containing private answer keys.
    return {
        "id": activity.id,
        "conceptId": activity.concept_id,
        "difficulty": activity.difficulty,
        "status": activity.status,
        "hintUsed": activity.hinted,
        **activity.public,
    }


def retrieve(db, services, course_id, owner_id, query, limit=5, release_id=None):
    from learnloop.persistence.releases import get_release, released_documents

    release = get_release(db, course_id, release_id)
    if not release:
        return []
    release_id = release.id
    documents = released_documents(db, course_id, release_id)
    ids = services.search(query, owner_id, course_id, [d.id for d in documents], limit)
    chunks = grounding_chunks(db, course_id, owner_id, ids, release_id)
    return [chunks[id] for id in ids if id in chunks]


def curriculum_order(concepts, edges):
    """Stable prerequisite order, preferring foundations before applications."""
    ranks = {"basic": 0, "intermediate": 1, "advanced": 2}
    pending = list(concepts)
    known = {c["id"] for c in concepts}
    parents = {c["id"]: set() for c in concepts}
    for e in edges:
        if e["dependent"] in parents and e["prerequisite"] in known:
            parents[e["dependent"]].add(e["prerequisite"])
    result, done = [], set()
    while pending:
        eligible = [c for c in pending if parents[c["id"]] <= done]
        if not eligible:
            return concepts  # Legacy invalid maps remain readable.
        chosen = min(eligible, key=lambda c: ranks.get((c.get("curriculum") or {}).get("layer"), 1))
        result.append(chosen)
        done.add(chosen["id"])
        pending.remove(chosen)
    return result
