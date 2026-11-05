import math
from concurrent.futures import ThreadPoolExecutor

from learnloop.agents.grounding import GROUNDING_PROMPT, generate_grounded
from learnloop.core.domain import DIFFICULTIES, validate_graph
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import grounding_valid, validate_sources
from learnloop.core.schemas import DifficultyMaterials, Graph
from learnloop.evaluation.artifacts import checkpoint, digest, freeze, prompt_key, thaw
from learnloop.evaluation.provider import usage
from learnloop.evaluation.schema import EXPERTS, ExamDraft, ExamItem, Screening, Unit
from learnloop.evaluation.variants import EXPERT, instruction


def reviewed_generation(unit, provider, role, prompt, context, output, path):
    key = digest(
        {
            "unit": unit.model_dump(),
            "model": provider.model,
            "temperature": provider.temperature,
            "seed": provider.seed,
            "prompt": prompt,
            "groundingPrompt": GROUNDING_PROMPT,
            "context": context,
            "schema": output.model_json_schema(),
            "mode": "fixture" if provider.offline else "live",
        }
    )
    if path.exists():
        saved = thaw(path)["payload"]
        if saved["key"] != key:
            raise ValueError("Preparation checkpoint changed; use a new bundle")
        return output.model_validate(saved["content"]), saved["grounding"]
    try:
        candidate, receipt = generate_grounded(
            provider, role, prompt, context, output, unit.chunks()
        )
    except ServiceError as error:
        checkpoint(
            path.with_name(path.stem + "-needs-review.json"),
            {
                "key": key,
                "status": "needs_review",
                "code": error.code,
                "review": error.details or {"message": error.message},
            },
        )
        raise
    try:
        freeze(path, {"key": key, "content": candidate.model_dump(), "grounding": receipt})
    except FileExistsError:
        saved = thaw(path)["payload"]
        if saved["key"] != key:
            raise ValueError("Concurrent preparation used different settings") from None
        return output.model_validate(saved["content"]), saved["grounding"]
    return candidate, receipt


def validate_exams(unit, payload):
    ids = {c.id for c in unit.graph.concepts}
    prompts, keys = set(), set()
    for phase in ("pre", "post"):
        coverage = set()
        for raw in payload[phase]:
            item = ExamItem.model_validate(raw)
            pair = (item.conceptId, item.question.difficulty)
            if item.conceptId not in ids or pair in coverage or item.id in keys:
                raise ValueError("Duplicate or unknown exam coverage/identity")
            coverage.add(pair)
            keys.add(item.id)
            key = prompt_key(raw["question"])
            if key in prompts or not item.question.rubric:
                raise ValueError("Exams need distinct prompts and complete private rubrics")
            prompts.add(key)
            validate_sources(item.question, unit.chunks())
        if coverage != {(id, level) for id in ids for level in DIFFICULTIES}:
            raise ValueError("Each exam must cover every concept at all three levels")


def author_exams(unit, provider, destination):
    result = {
        "unitHash": digest(unit.model_dump()),
        "pre": [],
        "post": [],
        "mode": "workflow_only" if provider.offline else "live",
    }
    for concept in unit.graph.concepts:
        passages = [
            p.model_dump() for p in unit.passages if p.id in {s.chunkId for s in concept.sources}
        ]
        draft, _ = reviewed_generation(
            unit,
            provider,
            "TestAuthor",
            "Author two independent exams: pre and post, each with one Basic, Intermediate and Advanced question for this concept. Use new prompts, cases and numbers for each exam. Provide source-backed rubrics/reference answers as requested. These are held-out tests, never teaching resources. Do not reveal or reuse test content outside this task.",
            {
                "concept": concept.model_dump(),
                "passages": [{"chunkId": p["id"], "text": p["text"]} for p in passages],
            },
            ExamDraft,
            destination.parent / "drafts" / "exams" / f"{concept.id}.json",
        )
        for phase in ("pre", "post"):
            for question in getattr(draft, phase):
                result[phase].append(
                    {
                        "id": f"{phase}-{concept.id}-{question.difficulty}",
                        "conceptId": concept.id,
                        "question": question.model_dump(),
                    }
                )
    validate_exams(unit, result)
    result["usage"] = usage(provider.calls)
    return freeze(destination, result)


def build_expert(unit, exams, variant, provider, destination, workers=1):
    if variant not in EXPERTS:
        raise ValueError("Unknown Expert variant")
    # Expert only receives course source/concept data, never the exam bank.
    graph, _ = reviewed_generation(
        unit,
        provider,
        "Expert",
        "Construct the requested graph using every supplied concept ID exactly once. Preserve concept targets and course scope, validate prerequisite ordering and cite sources. "
        + EXPERT[variant],
        {
            "concepts": unit.graph.model_dump()["concepts"],
            "referencePrerequisites": unit.graph.model_dump()["prerequisites"],
            "passages": [{"chunkId": p.id, "text": p.text} for p in unit.passages],
        },
        Graph,
        destination.parent / "drafts" / variant / "graph.json",
    )
    if {c.id for c in graph.concepts} != {c.id for c in unit.graph.concepts}:
        raise ValueError("Expert graph changed the controlled concept coverage")
    if {c.id: c.targetDifficulty for c in graph.concepts} != {
        c.id: c.targetDifficulty for c in unit.graph.concepts
    }:
        raise ValueError("Expert graph changed controlled targets")
    validate_graph(graph)
    materials = {}
    held_out = {prompt_key(item["question"]) for phase in ("pre", "post") for item in exams[phase]}

    def build_one(concept, child):
        ids = {s.chunkId for s in concept.sources}
        pack, receipt = reviewed_generation(
            unit,
            child,
            "Expert",
            instruction("Expert", variant),
            {
                "concept": concept.model_dump(),
                "passages": [
                    {"chunkId": p.id, "text": p.text} for p in unit.passages if p.id in ids
                ],
            },
            DifficultyMaterials,
            destination.parent / "drafts" / variant / f"{concept.id}.json",
        )
        if any(prompt_key(q.model_dump()) in held_out for q in pack.tests):
            raise ValueError("Training/test prompt overlap; reject this frozen artifact")
        return concept.id, {"content": pack.model_dump(), "grounding": receipt}

    if workers == 1:
        for concept in graph.concepts:
            id, pack = build_one(concept, provider)
            materials[id] = pack
    else:
        if workers not in (2, 3):
            raise ValueError("Preparation supports one to three bounded workers")
        children = [provider.partition(c.id, len(graph.concepts)) for c in graph.concepts]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(build_one, c, p) for c, p in zip(graph.concepts, children)]
            for future in futures:
                id, pack = future.result()
                materials[id] = pack
        for child in children:
            provider.calls.extend(child.calls)
    result = {
        "unitHash": digest(unit.model_dump()),
        "examHash": digest(exams),
        "variant": variant,
        "promptHash": digest(instruction("Expert", variant)),
        "graph": graph.model_dump(),
        "materials": materials,
        "mode": "workflow_only" if provider.offline else "live",
        "model": provider.model,
        "temperature": provider.temperature,
        "seed": provider.seed,
        "usage": usage(provider.calls),
        "observedModels": sorted({c.get("resolvedModel", provider.model) for c in provider.calls}),
    }
    return freeze(destination, result)


def required_reviews(unit, exams, frozen):
    items = {"unit": digest(unit.model_dump()), "exams": digest(exams)}
    for variant, artifact in frozen.items():
        items[f"expert/{variant}/graph"] = digest(artifact["graph"])
        for id, pack in artifact["materials"].items():
            # Every flagged item plus a deterministic 10% unflagged sample, minimum one.
            items[f"expert/{variant}/{id}"] = digest(pack)
    return items


def screen(unit, frozen, providers, embed, embedding_model="configured", cache_dir=None):
    if len(providers) < 2 or len({p.model for p in providers}) < 2:
        raise ValueError("Research screening requires at least two distinct configured models")
    report = {
        "unitHash": digest(unit.model_dump()),
        "models": [p.model for p in providers],
        "embedding": embedding_model,
        "items": {},
    }
    for variant, artifact in frozen.items():
        for id, pack in artifact["materials"].items():
            cache_path = cache_dir / variant / f"{id}.json" if cache_dir is not None else None
            cache_key = digest(
                {
                    "unit": unit.model_dump(),
                    "graph": artifact["graph"],
                    "pack": pack,
                    "models": [p.model for p in providers],
                    "embedding": embedding_model,
                    "screeningVersion": 1,
                }
            )
            if cache_path is not None and cache_path.exists():
                saved = thaw(cache_path)["payload"]
                if saved["key"] != cache_key:
                    raise ValueError("Screening inputs changed; use a new screening cache")
                report["items"][f"expert/{variant}/{id}"] = saved["item"]
                continue
            judgments = [
                p.generate(
                    "Screening",
                    "Independently screen source grounding, conceptual correctness, difficulty suitability and prerequisite accuracy. Flag uncertainty or any issue for human review.",
                    {
                        "graph": artifact["graph"],
                        "item": pack["content"],
                        "passages": [{"chunkId": p.id, "text": p.text} for p in unit.passages],
                    },
                    Screening,
                ).model_dump()
                for p in providers
            ]
            content = pack["content"]
            source = " ".join(
                unit.chunks()[s["chunkId"]]["text"] for s in content["lesson"]["sources"]
            )
            left, right = embed(str(content["lesson"])), embed(source)
            if (
                len(left) != len(right)
                or not left
                or not all(math.isfinite(v) for v in left + right)
            ):
                raise ValueError("Invalid screening embeddings")
            denominator = math.sqrt(sum(v * v for v in left) * sum(v * v for v in right))
            similarity = sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0
            flagged = similarity < 0.6 or any(
                not all(
                    j[k] for k in ("supported", "appropriateDifficulty", "prerequisiteAccuracy")
                )
                for j in judgments
            )
            report["items"][f"expert/{variant}/{id}"] = {
                "hash": digest(pack),
                "flagged": flagged,
                "embeddingCosine": similarity,
                "judgments": judgments,
                "modelAgreement": len(
                    {
                        tuple(
                            j[k]
                            for k in ("supported", "appropriateDifficulty", "prerequisiteAccuracy")
                        )
                        for j in judgments
                    }
                )
                == 1,
            }
            if cache_path is not None:
                freeze(
                    cache_path,
                    {"key": cache_key, "item": report["items"][f"expert/{variant}/{id}"]},
                )
    report["usage"] = [{"model": p.model, **usage(p.calls)} for p in providers]
    return report


def research_review_requirements(unit, exams, frozen, screening):
    validate_exams(unit, exams)
    if (
        exams.get("mode") != "live"
        or set(frozen) != set(EXPERTS)
        or any(a.get("mode") != "live" for a in frozen.values())
    ):
        raise ValueError("Workflow fixtures are not research artifacts")
    if (
        screening.get("unitHash") != digest(unit.model_dump())
        or len(set(screening.get("models", []))) < 2
    ):
        raise ValueError("Missing current multi-model/embedding screening")
    required = required_reviews(unit, exams, frozen)
    selected = {"unit", "exams", *[k for k in required if k.endswith("/graph")]}
    for variant in EXPERTS:
        candidates = sorted(
            k for k in required if k.startswith(f"expert/{variant}/") and not k.endswith("/graph")
        )
        unflagged = []
        for key in candidates:
            item = screening.get("items", {}).get(key)
            if (
                not item
                or item.get("hash") != required[key]
                or not math.isfinite(item.get("embeddingCosine", float("nan")))
                or len(item.get("judgments", [])) < 2
            ):
                raise ValueError("Screening missing or stale for a frozen resource")
            if item["flagged"]:
                selected.add(key)
            else:
                unflagged.append(key)
        selected.update(
            sorted(unflagged, key=lambda k: digest(k))[: max(1, math.ceil(len(unflagged) * 0.1))]
        )
    return {key: required[key] for key in sorted(selected)}


def research_gate(unit, exams, frozen, screening, reviews):
    required = research_review_requirements(unit, exams, frozen, screening)
    for key in required:
        review = reviews.get(key, {})
        if (
            review.get("hash") != required[key]
            or review.get("decision") != "approved"
            or not review.get("reviewer", "").strip()
            or not review.get("notes", "").strip()
        ):
            raise ValueError(f"Human review required or stale: {key}")
    return sorted(required)


def load_bundle(root):
    unit = Unit.model_validate(thaw(root / "unit.json")["payload"])
    exams = thaw(root / "exams.json")["payload"]
    provenance_path = root / "release-provenance.json"
    if provenance_path.exists():
        provenance = thaw(provenance_path)["payload"]
        if provenance.get("unitHash") != digest(unit.model_dump()):
            raise ValueError("Release provenance belongs to a different course unit")
    validate_exams(unit, exams)
    if exams["unitHash"] != digest(unit.model_dump()):
        raise ValueError("Exam bank belongs to a different course unit")
    frozen = {v: thaw(root / f"expert-{v}.json")["payload"] for v in EXPERTS}
    for variant, item in frozen.items():
        if (
            item["unitHash"] != digest(unit.model_dump())
            or item["examHash"] != digest(exams)
            or item["variant"] != variant
        ):
            raise ValueError("Frozen artifacts do not belong to this unit/exam/variant")
        graph = Graph.model_validate(item["graph"])
        validate_graph(graph)
        validate_sources(graph, unit.chunks())
        ids = {c.id for c in unit.graph.concepts}
        if {c.id for c in graph.concepts} != ids or set(item["materials"]) != ids:
            raise ValueError("Frozen resource coverage differs from the controlled unit")
        held_out = {
            prompt_key(row["question"]) for phase in ("pre", "post") for row in exams[phase]
        }
        for pack in item["materials"].values():
            content = DifficultyMaterials.model_validate(pack["content"])
            validate_sources(content, unit.chunks())
            if not grounding_valid(pack["content"], unit.chunks(), pack["grounding"]):
                raise ValueError("Frozen source-review receipt is stale")
            if any(prompt_key(q.model_dump()) in held_out for q in content.tests):
                raise ValueError("Frozen training/test prompt overlap")
    return unit, exams, frozen
