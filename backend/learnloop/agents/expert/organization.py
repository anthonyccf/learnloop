"""Expert sub-agent calls with independent contexts and an atomic coordinator commit.

Concept IDs, resources and learner evidence are never rewritten by organization.
The source catalog fingerprint prevents stale organization being used or published.
"""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from learnloop.agents.expert.prompts import RELATION_PROMPT, REVIEW_PROMPT, TOPIC_PROMPT
from learnloop.core.domain import validate_graph
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import CourseRelationships, TopicOrganization
from learnloop.persistence.database import Chunk, Course, Document, Run
from learnloop.runtime.events import accept, pending, run_status, step

ORGANIZATION_VERSION = 1


def catalog_signature(concepts):
    canonical = sorted(concepts, key=lambda c: c["id"])
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def current_organization(documents, concepts):
    signature = catalog_signature(concepts)
    for doc in documents:
        organization = doc.graph.get("organization", {})
        if (
            organization.get("version") == ORGANIZATION_VERSION
            and organization.get("signature") == signature
        ):
            return organization
    return None


def validate_topics(concepts, topics):
    ids = {c["id"] for c in concepts}
    members = [id for topic in topics for id in topic["conceptIds"]]
    if (
        set(members) != ids
        or len(members) != len(ids)
        or len({t["id"] for t in topics}) != len(topics)
    ):
        raise ServiceError(
            "invalid_organization", "Topic groups must contain every concept exactly once.", True
        )


def normalize_related(concepts, relationships):
    """Remove redundant related links without inventing or weakening prerequisites."""
    ids = {c["id"] for c in concepts}
    result = copy.deepcopy(relationships)
    prerequisites = {
        frozenset((e["prerequisite"], e["dependent"])) for e in result["prerequisites"]
    }
    seen, related = set(), []
    removed = {"duplicateRelated": 0, "prerequisiteOverlap": 0}
    for edge in result["related"]:
        first, second = edge["first"], edge["second"]
        if first == second or first not in ids or second not in ids:
            raise ServiceError(
                "invalid_organization",
                f"Related link {first} <-> {second} must connect two distinct known concepts.",
                True,
            )
        pair = frozenset((first, second))
        if pair in prerequisites:
            removed["prerequisiteOverlap"] += 1
        elif pair in seen:
            removed["duplicateRelated"] += 1
        else:
            related.append(edge)
            seen.add(pair)
    result["related"] = related
    return result, removed


def constrain_review(review, proposals):
    """A reviewer can prune proposals, never expand its prerequisite authority."""
    result = copy.deepcopy(review)
    allowed = {(e["prerequisite"], e["dependent"]) for e in proposals["prerequisites"]}
    result["prerequisites"] = [
        e for e in result["prerequisites"] if (e["prerequisite"], e["dependent"]) in allowed
    ]
    return result, len(review["prerequisites"]) - len(result["prerequisites"])


def validate_organization(concepts, topics, relationships, source_ids, proposals=None):
    """Hard structural checks only; semantic review is a separate model call."""
    validate_topics(concepts, topics)
    ids = {c["id"] for c in concepts}
    validate_graph({"concepts": concepts, "prerequisites": relationships["prerequisites"]})
    candidate_pairs = (
        {(e["prerequisite"], e["dependent"]) for e in proposals["prerequisites"]}
        if proposals
        else None
    )
    for edge in relationships["prerequisites"]:
        if (
            not edge["sourceChunkIds"]
            or not set(edge["sourceChunkIds"]) <= source_ids
            or candidate_pairs is not None
            and (edge["prerequisite"], edge["dependent"]) not in candidate_pairs
        ):
            raise ServiceError(
                "invalid_organization",
                "Reviewed prerequisite references must match supplied evidence and proposals.",
                True,
            )
    pairs = set()
    prerequisite_pairs = {
        frozenset((e["prerequisite"], e["dependent"])) for e in relationships["prerequisites"]
    }
    for edge in relationships["related"]:
        pair = frozenset((edge["first"], edge["second"]))
        if len(pair) != 2 or not pair <= ids or pair in pairs or pair in prerequisite_pairs:
            raise ServiceError(
                "invalid_organization",
                f"Invalid related link {edge['first']} <-> {edge['second']}: expected a distinct known pair, without duplicates or prerequisite overlap.",
                True,
            )
        pairs.add(pair)


def organize_course(factory, services, run_id, document_id):
    with factory() as db:
        anchor = db.get(Document, document_id)
        documents = list(
            db.scalars(
                select(Document)
                .where(
                    Document.course_id == anchor.course_id,
                    Document.status.in_(("prepared", "published")),
                )
                .order_by(Document.id)
            )
        )
        concepts = [c for doc in documents for c in doc.graph.get("concepts", [])]
        if not concepts:
            return
        if current_organization(documents, concepts):
            return
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.document_id.in_([d.id for d in documents]))
                .order_by(Chunk.document_id, Chunk.ordinal)
            )
        )
        checkpoint = copy.deepcopy(db.get(Run, run_id).input.get("organizationDraft", {}))
        course_id = anchor.course_id
        existing = [e for doc in documents for e in doc.graph.get("prerequisites", [])]
    signature = catalog_signature(concepts)
    if checkpoint.get("signature") != signature:
        checkpoint = {"signature": signature}
    aliases = {c["id"]: f"c{i}" for i, c in enumerate(concepts)}
    source_aliases = {c.id: f"s{i}" for i, c in enumerate(chunks)}
    chunk_map = {c.id: c for c in chunks}
    compact = [
        {
            "id": aliases[c["id"]],
            "title": c["title"],
            "summary": c["summary"],
            "sources": [
                {
                    "id": source_aliases[s["chunkId"]],
                    "page": chunk_map[s["chunkId"]].page,
                    "document": chunk_map[s["chunkId"]].document_id,
                    "excerpt": s["quote"],
                }
                for s in c["sources"]
                if s["chunkId"] in source_aliases
            ],
        }
        for c in concepts
    ]
    context = {
        "concepts": compact,
        "existingPrerequisites": [
            {"prerequisite": aliases[e["prerequisite"]], "dependent": aliases[e["dependent"]]}
            for e in existing
            if e["prerequisite"] in aliases and e["dependent"] in aliases
        ],
    }

    def save(name, result, label):
        checkpoint[name] = result
        with factory.begin() as db:
            run = db.get(Run, run_id)
            run.input = {**run.input, "organizationDraft": checkpoint}
            step(
                db,
                run_id,
                "expert",
                label,
                "Completed an independent whole-course organization task.",
                "publish_resources",
            )

    with factory.begin() as db:
        run_status(
            db,
            run_id,
            "running",
            "Expert sub-agents are organizing topics and reviewing course-wide relationships.",
        )
    # Independent calls: neither analyst sees the other's output.
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = []
        for name, prompt, schema, label in [
            ("topics", TOPIC_PROMPT, TopicOrganization, "Course Organizer: group all concepts"),
            (
                "relationships",
                RELATION_PROMPT,
                CourseRelationships,
                "Relationship Analyst: connect concepts across sections",
            ),
        ]:
            if name not in checkpoint:
                tasks.append(
                    (name, pool.submit(services.generate, "Expert", prompt, context, schema), label)
                )
        for name, future, label in tasks:
            save(name, future.result().model_dump(), label)
    if "review" not in checkpoint:
        evidence_ids = {
            s for e in checkpoint["relationships"]["prerequisites"] for s in e["sourceChunkIds"]
        }
        review_context = {
            **context,
            "proposals": checkpoint["relationships"],
            "validationFeedback": checkpoint.get("validationError"),
            "passages": [
                {"id": source_aliases[c.id], "page": c.page, "text": c.text}
                for c in chunks
                if source_aliases[c.id] in evidence_ids
            ],
        }
        save(
            "review",
            services.generate(
                "Expert", REVIEW_PROMPT, review_context, CourseRelationships
            ).model_dump(),
            "Relationship Reviewer: check essential prerequisites",
        )
    alias_concepts = [{**c, "id": aliases[c["id"]]} for c in concepts]
    stage = "topics"
    try:
        validate_topics(alias_concepts, checkpoint["topics"]["topics"])
        stage = "relationships"
        constrained, discarded = constrain_review(checkpoint["review"], checkpoint["relationships"])
        relationships, removed = normalize_related(alias_concepts, constrained)
        removed["unproposedPrerequisites"] = discarded
        validate_organization(
            alias_concepts,
            checkpoint["topics"]["topics"],
            relationships,
            set(source_aliases.values()),
            checkpoint["relationships"],
        )
    except ServiceError as error:
        # Keep a bounded diagnostic history and retry only the invalid stage.
        with factory.begin() as db:
            run = db.get(Run, run_id)
            inputs = copy.deepcopy(run.input)
            history = inputs.setdefault("failedOrganizationDrafts", [])
            history.append(
                {"stage": stage, "error": error.message, "draft": copy.deepcopy(checkpoint)}
            )
            inputs["failedOrganizationDrafts"] = history[-3:]
            checkpoint.pop("topics" if stage == "topics" else "review", None)
            checkpoint["validationError"] = {"stage": stage, "message": error.message}
            inputs["organizationDraft"] = checkpoint
            run.input = inputs
        raise ServiceError(error.code, error.message, True) from error
    reverse = {alias: id for id, alias in aliases.items()}
    reverse_sources = {alias: id for id, alias in source_aliases.items()}
    topics = [
        {
            **t,
            "id": f"{document_id}:{t['id']}",
            "conceptIds": [reverse[id] for id in t["conceptIds"]],
        }
        for t in checkpoint["topics"]["topics"]
    ]
    prerequisites = [
        {
            **e,
            "prerequisite": reverse[e["prerequisite"]],
            "dependent": reverse[e["dependent"]],
            "sourceChunkIds": [reverse_sources[s] for s in e["sourceChunkIds"]],
        }
        for e in relationships["prerequisites"]
    ]
    related = [
        {**e, "first": reverse[e["first"]], "second": reverse[e["second"]]}
        for e in relationships["related"]
    ]
    organization = {
        "version": ORGANIZATION_VERSION,
        "signature": signature,
        "topics": topics,
        "prerequisites": prerequisites,
        "related": related,
        "normalization": removed,
        "coverage": {
            "conceptCount": len(concepts),
            "groupedConceptCount": sum(len(t["conceptIds"]) for t in topics),
            "documentCount": len(documents),
            "topicCount": len(topics),
            "reviewed": True,
        },
    }
    with factory.begin() as db:
        db.scalar(select(Course).where(Course.id == course_id).with_for_update())
        latest = list(
            db.scalars(
                select(Document).where(
                    Document.course_id == course_id, Document.status.in_(("prepared", "published"))
                )
            )
        )
        if (
            catalog_signature([c for doc in latest for c in doc.graph.get("concepts", [])])
            != signature
        ):
            raise ServiceError(
                "catalog_changed",
                "Course concepts changed during organization. Retrying against the updated catalog.",
                True,
            )
        anchor = db.get(Document, document_id)
        pending(db, run_id, "course_resources")
        anchor.graph = {**anchor.graph, "organization": organization}
        accept(db, run_id, "course_resources")
        step(
            db,
            run_id,
            "expert",
            "Expert Coordinator: publish organized map",
            f"Grouped {len(concepts)}/{len(concepts)} concepts into {len(topics)} topics; reviewed {len(prerequisites)} prerequisites and {len(related)} related links. Saved concept IDs and learner evidence retained.",
            "publish_resources",
            "completed",
        )
