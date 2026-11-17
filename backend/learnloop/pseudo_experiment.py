"""Bounded exploratory evaluation for a saved workbench configuration."""

from itertools import zip_longest

from learnloop.agents.grounding import generate_grounded
from learnloop.core.domain import validate_graph
from learnloop.core.grounding import validate_sources
from learnloop.core.schemas import DifficultyMaterials, Graph
from learnloop.evaluation.artifacts import checkpoint, digest, freeze, prompt_key
from learnloop.evaluation.metrics import analyze
from learnloop.evaluation.prepare import author_exams, validate_exams
from learnloop.evaluation.provider import Provider, usage
from learnloop.evaluation.runner import run_episode
from learnloop.evaluation.schema import ExperimentConfig, Passage, Unit
from learnloop.evaluation.variants import instruction


def make_unit(setup, release, count):
    if setup["material"]["id"] == "__all__":
        documents = release["documents"]
        if count < len(documents):
            raise ValueError("At least one concept per published material is required.")
        originals = []
        seen = set()
        for layer in zip_longest(*(d["graph"]["concepts"] for d in documents)):
            for concept in layer:
                if concept is not None and concept["id"] not in seen:
                    originals.append(concept)
                    seen.add(concept["id"])
        originals = originals[:count]
        total_concepts = len(seen)
        covered = {
            release["chunks"][source["chunkId"]]["document_id"]
            for concept in originals
            for source in concept["sources"]
        }
        if any(doc["id"] not in covered for doc in documents):
            raise ValueError(
                "The selected concepts do not cite every material; choose a larger concept limit."
            )
    else:
        doc = next(d for d in release["documents"] if d["id"] == setup["material"]["id"])
        all_concepts = doc["graph"]["concepts"]
        originals = all_concepts[:count]
        total_concepts = len(all_concepts)
    if not originals:
        raise ValueError("The selected published material has no concepts.")
    mapping = {c["id"]: f"c{i + 1:02}" for i, c in enumerate(originals)}
    selected_ids = {s["chunkId"] for c in originals for s in c["sources"]}
    links = [e for e in release["graph"]["prerequisites"] if e["dependent"] in mapping]
    for edge in links:
        if edge["prerequisite"] in mapping:
            selected_ids.update(edge.get("sourceChunkIds", []))
            if edge.get("source"):
                selected_ids.add(edge["source"]["chunkId"])
    passages = {id: f"p{i + 1:02}" for i, id in enumerate(sorted(selected_ids))}
    concepts = [
        {
            "id": mapping[c["id"]],
            "title": c["title"],
            "summary": c["summary"],
            "sources": [
                {"chunkId": passages[s["chunkId"]], "quote": s["quote"]} for s in c["sources"]
            ],
            "targetDifficulty": c.get("targetDifficulty", "intermediate"),
        }
        for c in originals
    ]
    edges = []
    for edge in links:
        if edge["prerequisite"] not in mapping:
            continue
        source_id = (edge.get("sourceChunkIds") or [edge.get("source", {}).get("chunkId")])[0]
        source = edge.get("source") or {
            "chunkId": source_id,
            "quote": release["chunks"][source_id]["text"][:200],
        }
        edges.append(
            {
                "prerequisite": mapping[edge["prerequisite"]],
                "dependent": mapping[edge["dependent"]],
                "source": {"chunkId": passages[source["chunkId"]], "quote": source["quote"]},
            }
        )
    graph = Graph.model_validate({"concepts": concepts, "prerequisites": edges})
    source_passages = [
        Passage.model_validate(
            {
                "id": new_id,
                "text": release["chunks"][id]["text"],
                "page": release["chunks"][id]["page"],
                "document": release["chunks"][id]["label"],
            }
        )
        for id, new_id in passages.items()
    ]
    # Exploratory runs explicitly support fewer than the research minimum of 10 concepts.
    warnings = []
    if any(e["prerequisite"] not in mapping for e in links):
        warnings.append("Prerequisites outside the selected subset are not simulated.")
    if len(originals) < total_concepts:
        warnings.append(
            f"This test samples {len(originals)} of {total_concepts} published concepts in the selected material scope."
        )
    unit = Unit.model_construct(
        id="exploratory-unit",
        title=setup["material"]["filename"],
        sourceSha256=setup["material"]["sha256"],
        passages=source_passages,
        graph=graph,
        scopeWarnings=warnings,
    )
    validate_graph(graph)
    validate_sources(graph, unit.chunks())
    return unit


class RoutedProvider:
    """Apply captured templates/models without changing simulator or test-author prompts."""

    def __init__(self, base, templates, learner=None):
        self.base, self.templates, self.learner = base, templates, learner

    def __getattr__(self, name):
        return getattr(self.base, name)

    def generate(self, role, prompt, context, output):
        agent = {"Expert": "expert", "Tutoring": "tutor", "Assessing": "assessing"}.get(role)
        template = self.templates.get(agent) if agent else None
        stages = {
            ("Expert", "DifficultyMaterials"): ("lesson", "questions"),
            ("Tutoring", "PlanChoice"): ("analysis",),
            ("Assessing", "Assessment"): ("analysis", "lesson", "questions"),
        }.get((role, output.__name__), ())
        if template and stages:
            additions = [template.get("prompts", {}).get(stage, "").strip() for stage in stages]
            prompt += "\n\nSelected workbench template instructions:\n" + "\n\n".join(
                filter(None, additions)
            )
        old_model, old_temp = self.base.model, self.base.temperature
        try:
            requested = (
                self.learner.get("model")
                if role == "Simulator" and self.learner
                else template.get("model")
                if template
                else None
            )
            if requested and requested != "configured":
                self.base.model = requested
            if template and template.get("temperature") is not None:
                self.base.temperature = template["temperature"]
            return self.base.generate(role, prompt, context, output)
        finally:
            self.base.model, self.base.temperature = old_model, old_temp


def run(setup, release, output, config, settings, provider_cls=Provider, reused=None):
    output.mkdir(parents=True, exist_ok=True)

    def status(phase):
        checkpoint(output / "status.json", {"status": "running", "phase": phase})

    if reused:
        raw_unit = reused["unit"]
        unit = Unit.model_construct(
            **{
                **raw_unit,
                "graph": Graph.model_validate(raw_unit["graph"]),
                "passages": [Passage.model_validate(item) for item in raw_unit["passages"]],
            }
        )
        validate_graph(unit.graph)
        validate_sources(unit.graph, unit.chunks())
    else:
        unit = make_unit(setup, release, config["concepts"])
    freeze(output / "unit.json", unit.model_dump())
    freeze(output / "setup.json", setup)
    templates = setup.get("templates") or {}
    versions = {
        key: (templates.get(agent) or {}).get("basePrompts", "v1")
        for key, agent in (("expert", "expert"), ("tutor", "tutor"), ("assessor", "assessing"))
    }
    if reused:
        status("Loading prepared material")
        exams, artifact = reused["exams"], reused["expert"]
        validate_exams(unit, exams)
        if (
            exams.get("unitHash") != digest(unit.model_dump())
            or artifact.get("graph") != unit.graph.model_dump()
        ):
            raise ValueError("Prepared material does not match the frozen unit.")
        heldout = {
            prompt_key(item["question"]) for phase in ("pre", "post") for item in exams[phase]
        }
        for concept in unit.graph.concepts:
            pack = DifficultyMaterials.model_validate(artifact["materials"][concept.id]["content"])
            validate_sources(pack, unit.chunks())
            if any(prompt_key(q.model_dump()) in heldout for q in pack.tests):
                raise ValueError("Training question overlaps a held-out test.")
        freeze(output / "exams.json", exams)
        freeze(output / "expert.json", artifact)
        preparation_usage = usage([])
    else:
        status("Preparing independent tests")
        prep_base = provider_cls(
            settings,
            output / "preparation-calls",
            max_calls=80 * config["concepts"],
            max_tokens=400000 * config["concepts"],
        )
        prep = RoutedProvider(prep_base, setup["templates"])
        exams = author_exams(unit, prep, output / "exams.json")["payload"]
        heldout = {
            prompt_key(item["question"]) for phase in ("pre", "post") for item in exams[phase]
        }
        materials = {}
        for concept in unit.graph.concepts:
            status("Preparing teaching material: " + concept.title)
            pack, _ = generate_grounded(
                prep,
                "Expert",
                instruction("Expert", "grounded", versions["expert"]),
                {
                    "concept": concept.model_dump(),
                    "passages": [
                        {"chunkId": p.id, "text": p.text}
                        for p in unit.passages
                        if p.id in {s.chunkId for s in concept.sources}
                    ],
                },
                DifficultyMaterials,
                unit.chunks(),
            )
            if any(prompt_key(q.model_dump()) in heldout for q in pack.tests):
                raise ValueError("Training question overlaps a held-out test.")
            materials[concept.id] = {"content": pack.model_dump()}
        artifact = {"mode": "exploratory", "graph": unit.graph.model_dump(), "materials": materials}
        freeze(output / "expert.json", artifact)
        preparation_usage = usage(prep.calls)
    config_obj = ExperimentConfig(
        activities=config["activities"],
        repeats=1,
        maxCalls=64,
        maxTokens=250000,
        model=settings.llm_model,
    )
    variants = {"expert": "grounded", "tutor": "utility", "assessor": "weighted"}
    changed = {key: version for key, version in versions.items() if version != "v1"}
    if changed:
        variants["promptVersions"] = changed
    conditions = (
        ("adaptive", "fixed_sequence", "memory_free") if config["baselines"] else ("adaptive",)
    )
    results = []
    for learner in setup["learners"]:
        spec = {
            "ability": [learner["basic"], learner["intermediate"], learner["advanced"]],
            "hint": learner["hint"],
            "gain": learner["gain"],
            "delay": learner["delaySeconds"] * 1000,
            "misconceptions": learner["misconceptions"],
        }
        for condition in conditions:
            status(f"Testing {learner['name']}: {condition}")
            root = output / "episodes" / digest([learner["id"], condition])[:16]
            base = provider_cls(settings, root / "calls", max_calls=64, max_tokens=250000)
            result = run_episode(
                unit,
                exams,
                artifact,
                variants,
                learner["id"],
                0,
                condition,
                config_obj,
                RoutedProvider(base, setup["templates"], learner),
                root,
                mode="exploratory",
                student_spec=spec,
            )
            result["learnerName"] = learner["name"]
            results.append(result)
    report = {
        "mode": "exploratory",
        "notResearchEvidence": True,
        "conceptCount": len(unit.graph.concepts),
        "scopeWarnings": unit.scopeWarnings,
        "preparationUsage": preparation_usage,
        "reusedSourceRunId": config.get("sourceRunId"),
        "promptVersions": versions,
        **analyze(results),
        "results": results,
    }
    freeze(output / "report.json", report)
    return report
