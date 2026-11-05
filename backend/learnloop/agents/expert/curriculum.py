"""Course-wide, checkpointed curriculum scopes; lesson layers are not mastery targets."""

import copy

from sqlalchemy import select

from learnloop.agents.expert.organization import current_organization
from learnloop.agents.expert.prompts import CURRICULUM_PROMPT
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import CurriculumPlan
from learnloop.persistence.database import Course, Document, Run
from learnloop.runtime.events import step

LEVELS = {"basic": 0, "intermediate": 1, "advanced": 2}


def validate_curriculum(plan, concepts, edges):
    items = plan["objectives"]
    ids = {c["id"] for c in concepts}
    by_id = {i["conceptId"]: i for i in items}
    if set(by_id) != ids or len(items) != len(ids):
        raise ServiceError(
            "invalid_curriculum",
            f"Assign every objective exactly once. Missing: {sorted(ids - set(by_id))}; unknown: {sorted(set(by_id) - ids)}; duplicate IDs: {sorted({i['conceptId'] for i in items if sum(j['conceptId'] == i['conceptId'] for j in items) > 1})}.",
            True,
        )
    parents = {id: set() for id in ids}
    for e in edges:
        parents[e["dependent"]].add(e["prerequisite"])
    counts = [sum(i["layer"] == level for i in items) for level in LEVELS]
    if counts[0] < counts[1] or counts[1] < counts[2]:
        raise ServiceError(
            "invalid_curriculum",
            "The pyramid must taper: basic count >= intermediate count >= advanced count. Preserve supported scope; do not invent or discard goals.",
            True,
        )
    scopes = set()
    for item in items:
        id, level = item["conceptId"], LEVELS[item["layer"]]
        if set(item["assumes"]) != parents[id] or len(item["assumes"]) != len(parents[id]):
            raise ServiceError(
                "invalid_curriculum",
                f"{id}: assumes must match reviewed direct prerequisites.",
                True,
            )
        ranks = [LEVELS[by_id[p]["layer"]] for p in parents[id]]
        # Relationships are transitively reduced. A lower-layer foundation may
        # be an ancestor rather than an immediate parent of a later application.
        ancestors, pending = set(), list(parents[id])
        while pending:
            parent = pending.pop()
            if parent not in ancestors:
                ancestors.add(parent)
                pending.extend(parents[parent] - ancestors)
        connected_below = any(LEVELS[by_id[p]["layer"]] == level - 1 for p in ancestors)
        if any(r > level for r in ranks) or (level and not connected_below):
            raise ServiceError(
                "invalid_curriculum",
                f"{id}: higher lessons need a prerequisite path from the layer below; parents cannot be higher.",
                True,
            )
        scope = " ".join(item["teaches"].casefold().split())
        if scope in scopes:
            raise ServiceError("invalid_curriculum", "Teaching scopes must be distinct.", True)
        scopes.add(scope)


def prepare_curriculum(factory, services, run_id, document_id):
    with factory() as db:
        anchor = db.get(Document, document_id)
        course_id = anchor.course_id
        docs = list(
            db.scalars(
                select(Document).where(
                    Document.course_id == course_id, Document.status.in_(("prepared", "published"))
                )
            )
        )
        concepts = sorted(
            [c for d in docs for c in d.graph.get("concepts", [])], key=lambda c: c["id"]
        )
        organization = current_organization(docs, concepts)
        if not organization:
            raise ServiceError(
                "missing_organization",
                "Review course relationships before curriculum planning.",
                True,
            )
        signature = organization["signature"]
        if all(d.graph.get("curriculum", {}).get("signature") == signature for d in docs):
            return
        draft = copy.deepcopy(db.get(Run, run_id).input.get("curriculumDraft", {}))
    aliases = {c["id"]: f"c{i}" for i, c in enumerate(concepts)}
    reverse = {alias: id for id, alias in aliases.items()}
    alias_concepts = [
        {"id": aliases[c["id"]], "title": c["title"], "summary": c["summary"]} for c in concepts
    ]
    alias_edges = [
        {
            "prerequisite": aliases[e["prerequisite"]],
            "dependent": aliases[e["dependent"]],
            "rationale": e["rationale"],
        }
        for e in organization["prerequisites"]
    ]
    context = {"concepts": alias_concepts, "prerequisites": alias_edges}
    if draft.get("signature") != signature or draft.get("format") != 3:
        draft = {"signature": signature, "format": 3}

    def save(name, value):
        draft[name] = value
        with factory.begin() as db:
            r = db.get(Run, run_id)
            r.input = {**r.input, "curriculumDraft": copy.deepcopy(draft)}

    feedback = draft.get("validationFeedback")
    for attempt in range(3):
        plan = (
            draft.get("review")
            or draft.get("plan")
            or services.generate(
                "Expert",
                CURRICULUM_PROMPT,
                {**context, "validationFeedback": feedback},
                CurriculumPlan,
            ).model_dump()
        )
        try:
            validate_curriculum(plan, alias_concepts, alias_edges)
            save("plan", plan)
            # An independent review sees all scopes before any lesson is authored.
            plan = (
                draft.get("review")
                or services.generate(
                    "Expert",
                    CURRICULUM_PROMPT
                    + "\nAct as an independent curriculum reviewer. Audit the proposed plan for repeated teaching scopes, misplaced layers and absent new capabilities. Return a corrected complete plan. Preserve all objectives and reviewed prerequisite pairs.",
                    {**context, "proposedPlan": plan},
                    CurriculumPlan,
                ).model_dump()
            )
            validate_curriculum(plan, alias_concepts, alias_edges)
            save("review", plan)
            break
        except ServiceError as error:
            feedback = error.message
            draft.pop("plan", None)
            draft.pop("review", None)
            save("validationFeedback", feedback)
    else:
        raise ServiceError("invalid_curriculum", feedback, True)
    by_id = {
        reverse[i["conceptId"]]: {
            **i,
            "conceptId": reverse[i["conceptId"]],
            "assumes": [reverse[p] for p in i["assumes"]],
        }
        for i in plan["objectives"]
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
        current = current_organization(
            latest, [c for d in latest for c in d.graph.get("concepts", [])]
        )
        if not current or current["signature"] != signature:
            raise ServiceError(
                "catalog_changed", "Course changed during curriculum planning.", True
            )
        for doc in latest:
            graph = copy.deepcopy(doc.graph)
            old = graph.get("curriculum", {}).get("objectives", {})
            assignments = {c["id"]: by_id[c["id"]] for c in graph["concepts"]}
            for id, assignment in assignments.items():
                if old.get(id) != assignment:
                    graph.get("resources", {}).pop(id, None)
            graph["curriculum"] = {"version": 1, "signature": signature, "objectives": assignments}
            doc.graph = graph
        step(
            db,
            run_id,
            "expert",
            "Learning pyramid reviewed",
            "Assigned one exclusive teaching scope per objective with reviewed prerequisites before writing lessons.",
            "publish_resources",
        )
