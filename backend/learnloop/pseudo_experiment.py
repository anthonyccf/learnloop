"""Bounded exploratory evaluation for a saved workbench configuration."""

from itertools import zip_longest

from pydantic import Field, ValidationError

from learnloop.agents.expert.materials import material_content
from learnloop.agents.expert.slide_evidence import with_slide_evidence
from learnloop.core.domain import target_difficulty, validate_graph
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import remap_sources, source_ids, validate_sources
from learnloop.core.schemas import Concept, Graph, Lesson, PostLesson, Question
from learnloop.evaluation.artifacts import checkpoint, digest, freeze, prompt_key
from learnloop.evaluation.metrics import analyze
from learnloop.evaluation.prepare import author_exams, validate_exams
from learnloop.evaluation.provider import Provider, usage
from learnloop.evaluation.schema import ExperimentConfig, Passage, Unit
from learnloop.pseudo_control import raise_if_stopped
from learnloop.pseudo_workbench import WorkbenchSession, drive_episode


class WorkbenchConcept(Concept):
    """Workbench concept ids are document-scoped and do not use the research slug."""

    id: str = Field(min_length=1, max_length=100)


class WorkbenchGraph(Graph):
    concepts: list[WorkbenchConcept] = Field(min_length=1)


def published_unit(setup, release, count):
    """Sample the published course sequence and adapt Workbench packs for the simulator."""
    material_id = setup["material"]["id"]
    documents = [d for d in release["documents"] if material_id in ("__all__", d["id"])]
    catalog = release["graph"]["concepts"]
    scopes = []
    for document in documents:
        graph = document["graph"]
        ids = {c["id"] for c in graph["concepts"]} | set(graph.get("conceptAliases", {}).values())
        scopes.append([c["id"] for c in catalog if c["id"] in ids])
    if not scopes or any(not scope for scope in scopes):
        raise ValueError("Each selected material needs published concepts before it can be tested.")
    # Sample across files, then present the chosen goals in published order.
    sampled = dict.fromkeys(id for row in zip_longest(*scopes) for id in row if id is not None)
    chosen = set(list(sampled)[:count])
    if any(chosen.isdisjoint(scope) for scope in scopes):
        raise ValueError("Choose a larger concept limit to cover every selected material.")
    originals = [c for c in catalog if c["id"] in chosen]
    mapping = {c["id"]: c["id"] for c in originals}
    resources = {
        id: material_content(pack)
        for document in release["documents"]
        for id, pack in document["graph"].get("resources", {}).items()
        if id in mapping
    }
    if resources.keys() != chosen:
        raise ValueError(
            "The selected concepts need lessons and questions published from Workbench."
        )
    selected_ids = {s["chunkId"] for c in originals for s in c["sources"]}
    selected_ids.update(source_ids(list(resources.values())))
    links = [e for e in release["graph"]["prerequisites"] if e["dependent"] in mapping]
    chunks = with_slide_evidence(release["chunks"], release.get("slideEvidence"))
    edges = []
    for edge in links:
        if edge["prerequisite"] not in mapping:
            continue
        source = edge.get("source")
        if not source:
            source_id = edge["sourceChunkIds"][0]
            source = {"chunkId": source_id, "quote": chunks[source_id]["text"][:200]}
        selected_ids.add(source["chunkId"])
        edges.append(
            {
                "prerequisite": mapping[edge["prerequisite"]],
                "dependent": mapping[edge["dependent"]],
                "source": source,
            }
        )
    passages = {chunk_id: chunk_id for chunk_id in sorted(selected_ids)}
    concepts = [
        {
            "id": mapping[c["id"]],
            "title": c["title"],
            "summary": c["summary"],
            "sources": remap_sources(c["sources"], passages),
            "targetDifficulty": target_difficulty(c),
        }
        for c in originals
    ]
    graph = WorkbenchGraph.model_validate(
        {"concepts": concepts, "prerequisites": remap_sources(edges, passages)}
    )
    source_passages = [
        Passage.model_validate(
            {
                "id": new_id,
                "text": chunks[id]["text"],
                "page": chunks[id]["page"],
                "document": chunks[id]["label"],
            }
        )
        for id, new_id in passages.items()
    ]
    # Exploratory runs explicitly support fewer than the research minimum of 10 concepts.
    warnings = []
    if any(e["prerequisite"] not in mapping for e in links):
        warnings.append("Prerequisites outside the selected subset are not simulated.")
    if len(originals) < len(sampled):
        warnings.append(
            f"This test samples {len(originals)} of {len(sampled)} published concepts in the selected material scope."
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
    materials = {}
    for id in mapping:
        saved = remap_sources(resources[id], passages)
        lesson = saved["lesson"]
        levels = saved.get("lessonsByDifficulty", {})
        pack = {
            "lesson": levels.get("intermediate", lesson),
            "basicLesson": levels.get("basic", lesson),
            "advancedLesson": levels.get("advanced", lesson),
            "tests": saved["tests"],
        }
        validate_pack(pack, unit.chunks())
        materials[mapping[id]] = {"content": pack}
    return unit, materials


def validate_pack(pack, chunks, heldout=()):
    # Earlier tests stored PostLesson drafts. New tests use the released Lesson
    # format, and both share the same question schema.
    for key in ("lesson", "basicLesson", "advancedLesson"):
        lesson = pack[key]
        (Lesson if "explanation" in lesson else PostLesson).model_validate(lesson)
    questions = [Question.model_validate(q) for q in pack["tests"]]
    if not questions or any(not q.rubric or not q.referenceAnswer for q in questions):
        raise ValueError("Practice questions need private reference answers and rubrics.")
    validate_sources(pack, chunks)
    if any(prompt_key(q.model_dump()) in heldout for q in questions):
        raise ValueError("Training question overlaps a held-out test.")


class RoutedProvider:
    """Apply captured templates/models without changing simulator or test-author prompts."""

    def __init__(self, base, templates, learner=None, training_prompts=None):
        self.base, self.templates, self.learner = base, templates, learner
        self.training_prompts = training_prompts

    def __getattr__(self, name):
        return getattr(self.base, name)

    def generate(self, role, prompt, context, output):
        agent = {"Expert": "expert", "Tutoring": "tutor", "Assessing": "assessing"}.get(role)
        template = self.templates.get(agent) if agent else None
        stages = {
            ("Expert", "Question"): ("questions",),
            ("Tutoring", "PlanChoice"): ("analysis",),
            ("Assessing", "Assessment"): ("analysis", "lesson", "questions"),
        }.get((role, output.__name__), ())
        if template and stages:
            additions = [template.get("prompts", {}).get(stage, "").strip() for stage in stages]
            prompt += "\n\nSelected workbench template instructions:\n" + "\n\n".join(
                filter(None, additions)
            )
        if role == "TestAuthor" and output.__name__ == "ExamDraft" and self.training_prompts:
            prompt += " Use different prompts and scenarios from the supplied practice questions."
            context = {
                **context,
                "practicePrompts": self.training_prompts[context["concept"]["id"]],
            }
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
            try:
                return self.base.generate(role, prompt, context, output)
            except ValidationError as error:
                if role == "Expert" and output is Question:
                    raise ServiceError(
                        "invalid_model_output",
                        "Write a valid source-backed practice question.",
                        False,
                    ) from error
                raise
        finally:
            self.base.model, self.base.temperature = old_model, old_temp


def episode_limits(concept_count, activities):
    exam_calls = 6 * concept_count
    max_calls = max(64, exam_calls + concept_count + 12 * activities + 16)
    max_tokens = max(250000, max_calls * 5000)
    return max_calls, max_tokens


def run(setup, release, output, config, settings, provider_cls=Provider, reused=None):
    output.mkdir(parents=True, exist_ok=True)

    def status(phase):
        checkpoint(output / "status.json", {"status": "running", "phase": phase})

    if reused:
        raw_unit = reused["unit"]
        unit = Unit.model_construct(
            **{
                **raw_unit,
                "graph": WorkbenchGraph.model_validate(raw_unit["graph"]),
                "passages": [Passage.model_validate(item) for item in raw_unit["passages"]],
            }
        )
        validate_graph(unit.graph)
        validate_sources(unit.graph, unit.chunks())
    else:
        unit, materials = published_unit(setup, release, config["concepts"])
    freeze(output / "unit.json", unit.model_dump())
    freeze(output / "setup.json", setup)
    versions = {key: "v2" for key in ("expert", "tutor", "assessor")}
    if reused:
        status("Loading prepared material")
        exams, artifact = reused["exams"], reused["expert"]
        validate_exams(unit, exams)
        if (
            exams.get("unitHash") != digest(unit.model_dump())
            or artifact.get("graph") != unit.graph.model_dump()
        ):
            raise ValueError("Prepared material does not match the frozen unit.")
        preparation_usage = usage([])
    else:
        prep_base = provider_cls(
            settings,
            output / "preparation-calls",
            max_calls=80 * len(unit.graph.concepts),
            max_tokens=400000 * len(unit.graph.concepts),
        )
        prep = RoutedProvider(prep_base, setup["templates"])
        training_prompts = {
            concept.id: [
                question["prompt"] for question in materials[concept.id]["content"]["tests"]
            ]
            for concept in unit.graph.concepts
        }
        artifact = {
            "mode": "exploratory",
            "materialSource": setup.get("materialSource", "workbench_generated"),
            "workbenchRunId": setup.get("workbenchRunId"),
            "graph": unit.graph.model_dump(),
            "materials": materials,
        }
        raise_if_stopped(output)
        status("Preparing independent exams")
        prep.training_prompts = training_prompts
        exams = author_exams(unit, prep, output / "exams.json")["payload"]
        preparation_usage = usage(prep.calls)
    heldout = {prompt_key(item["question"]) for phase in ("pre", "post") for item in exams[phase]}
    for concept in unit.graph.concepts:
        validate_pack(artifact["materials"][concept.id]["content"], unit.chunks(), heldout)
    if reused:
        freeze(output / "exams.json", exams)
    freeze(output / "expert.json", artifact)
    max_calls, max_tokens = episode_limits(len(unit.graph.concepts), config["activities"])
    config_obj = ExperimentConfig(
        activities=config["activities"],
        repeats=1,
        maxCalls=max_calls,
        maxTokens=max_tokens,
        model=settings.llm_model,
    )
    variants = {"expert": "grounded", "tutor": "utility", "assessor": "weighted"}
    variants["promptVersions"] = versions
    results = []
    with WorkbenchSession(
        settings, release, unit, setup, output / "workbench.db", artifact["materials"]
    ) as session:
        session.run_path = output
        for learner in setup["learners"]:
            raise_if_stopped(output)
            spec = {
                "ability": [learner["basic"], learner["intermediate"], learner["advanced"]],
                "hint": learner["hint"],
                "gain": learner["gain"],
                "delay": learner["delaySeconds"] * 1000,
                "misconceptions": learner["misconceptions"],
                "simulator": config.get("simulator", "controlled"),
            }
            status(f"Testing {learner['name']}")
            root = output / "episodes" / digest([learner["id"], "adaptive"])[:16]
            base = provider_cls(
                settings, root / "calls", max_calls=max_calls, max_tokens=max_tokens
            )
            result = drive_episode(
                session, unit, exams, artifact, variants, learner, config_obj, base, root, spec
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
