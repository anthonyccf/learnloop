"""Restart one failed exploratory episode from its original frozen inputs."""

import json

from learnloop.evaluation.artifacts import digest, runtime_hash, thaw
from learnloop.evaluation.prepare import validate_exams
from learnloop.evaluation.provider import Provider
from learnloop.evaluation.schema import ExperimentConfig, Passage, Unit
from learnloop.pseudo_experiment import WorkbenchGraph
from learnloop.pseudo_workbench import WorkbenchSession, drive_episode


def inputs(path, learner_id, condition, settings):
    setup = thaw(path / "input.json")["payload"]["setup"]
    learner = next((item for item in setup.get("learners", []) if item["id"] == learner_id), None)
    if learner is None:
        raise ValueError("Learner is not in this setup")
    root = path / "episodes" / digest([learner_id, condition])[:16]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    config = ExperimentConfig.model_validate(manifest["config"])
    if manifest["runtimeHash"] != runtime_hash():
        raise ValueError("Evaluation code changed since this episode")
    if config.model != settings.llm_model:
        raise ValueError("Backend model changed since this episode")
    raw = thaw(path / "unit.json")["payload"]
    unit = Unit.model_construct(
        **{
            **raw,
            "graph": WorkbenchGraph.model_validate(raw["graph"]),
            "passages": [Passage.model_validate(item) for item in raw["passages"]],
        }
    )
    exams, artifact = thaw(path / "exams.json")["payload"], thaw(path / "expert.json")["payload"]
    if (
        digest(unit.model_dump()) != manifest["unitHash"]
        or digest(exams) != manifest["examHash"]
        or digest(artifact) != manifest["resourceHash"]
    ):
        raise ValueError("Frozen evaluation materials changed")
    validate_exams(unit, exams)
    return setup, learner, root, manifest, config, unit, exams, artifact


def run_retry(path, learner_id, condition, destination, settings, provider_cls=Provider):
    setup, learner, _, manifest, config, unit, exams, artifact = inputs(
        path, learner_id, condition, settings
    )
    if condition != "adaptive":
        raise ValueError("Only the workbench session can be retried")
    release = thaw(path / "input.json")["payload"]["release"]
    base = provider_cls(
        settings,
        destination / "calls",
        seed=config.seed,
        temperature=config.temperature,
        max_calls=config.maxCalls,
        max_tokens=config.maxTokens,
    )
    with WorkbenchSession(
        settings, release, unit, setup, destination / "workbench.db", artifact["materials"]
    ) as session:
        session.run_path = path
        session.progress_path = destination / "retry-status.json"
        return drive_episode(
            session,
            unit,
            exams,
            artifact,
            manifest["variants"],
            learner,
            config,
            base,
            destination,
            manifest["studentSpec"],
        )
