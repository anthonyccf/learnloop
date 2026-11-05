from pathlib import Path

from learnloop.evaluation.artifacts import digest, freeze, read, runtime_hash, thaw
from learnloop.evaluation.metrics import analyze, latency_by_role
from learnloop.evaluation.prepare import load_bundle, research_gate
from learnloop.evaluation.provider import usage
from learnloop.evaluation.runner import run_episode
from learnloop.evaluation.schema import PROFILES
from learnloop.evaluation.variants import matrix


def run_matrix(
    bundle,
    output,
    config,
    provider_factory,
    *,
    offline=False,
    selected=None,
    baselines=False,
    retry_failed=False,
):
    unit, exams, artifacts = load_bundle(bundle)
    if not offline:
        if not (bundle / "screening.json").exists() or not (bundle / "reviews.json").exists():
            raise ValueError(
                "Research execution requires completed screening and recorded human reviews; no model calls were dispatched"
            )
        research_gate(
            unit,
            exams,
            artifacts,
            thaw(bundle / "screening.json")["payload"],
            thaw(bundle / "reviews.json")["payload"],
        )
    elif any(a.get("mode") != "workflow_only" for a in artifacts.values()):
        raise ValueError("Offline smoke must use explicitly labelled fixture artifacts")
    tasks = matrix() if selected is None else [selected]
    if selected is not None and selected not in matrix():
        raise ValueError("Unknown selected experimental configuration")
    baseline_modes = ("adaptive", "fixed_sequence", "memory_free") if baselines else ("adaptive",)
    if baselines and selected is None:
        raise ValueError("Baseline comparison requires one explicitly retained configuration")
    mode = "workflow_only" if offline else "research"
    manifest = {
        "config": config.model_dump(),
        "unitHash": digest(unit.model_dump()),
        "examHash": digest(exams),
        "resourceHashes": {k: digest(v) for k, v in artifacts.items()},
        "mode": mode,
        "runtimeHash": runtime_hash(),
        "tasks": tasks,
        "baselines": baseline_modes,
    }
    provenance = bundle / "release-provenance.json"
    if provenance.exists():
        manifest["courseRelease"] = thaw(provenance)["payload"]
    output = Path(output)
    if (output / "manifest.json").exists():
        if digest(thaw(output / "manifest.json")["payload"]) != digest(manifest):
            raise ValueError("Resume manifest changed; use a new output directory")
    else:
        freeze(output / "manifest.json", manifest)
    results = []
    for variants in tasks:
        if not offline and any(
            a["model"] != config.model or a["temperature"] != config.temperature
            for a in artifacts.values()
        ):
            raise ValueError("Model/temperature must remain fixed across experimental variants")
        for profile in PROFILES:
            for repeat in range(config.repeats):
                for baseline in baseline_modes:
                    task = {**variants, "profile": profile, "repeat": repeat, "baseline": baseline}
                    root = output / "episodes" / digest(task)[:24]
                    attempts = sorted(root.glob("attempt-*")) if root.exists() else []
                    prior = None
                    if attempts and (attempts[-1] / "result.json").exists():
                        prior = thaw(attempts[-1] / "result.json")["payload"]
                        if (
                            prior["variants"],
                            prior["profile"],
                            prior["repeat"],
                            prior["baseline"],
                        ) != (variants, profile, repeat, baseline):
                            raise ValueError("Episode identity mismatch")
                    if prior and (prior["status"] == "completed" or not retry_failed):
                        results.append(prior)
                        continue
                    if attempts and not retry_failed:
                        raise ValueError(
                            "Incomplete attempt retained; use --retry-failed to restart from the same initial profile"
                        )
                    if len(attempts) >= 3:
                        raise ValueError("Three-attempt episode retry limit reached")
                    destination = root / f"attempt-{len(attempts) + 1:02}"
                    provider = provider_factory(destination / "calls")
                    if bool(provider.offline) != offline:
                        raise ValueError("Provider mode does not match experiment mode")
                    results.append(
                        run_episode(
                            unit,
                            exams,
                            artifacts[variants["expert"]],
                            variants,
                            profile,
                            repeat,
                            baseline,
                            config,
                            provider,
                            destination,
                            mode=mode,
                        )
                    )
    report = {
        **analyze(results),
        "mode": mode,
        "manifestHash": digest(manifest),
        "results": results,
        "preparationUsage": {k: a["usage"] for k, a in artifacts.items()},
        "preparationLedgerUsage": usage(
            [read(path) for path in (bundle / "preparation-calls").rglob("call-*.json")]
        ),
        "latencyByRole": latency_by_role(
            [call for result in results for call in result.get("usageLedger", [])]
        ),
        "observedModels": sorted(
            {
                call.get("resolvedModel", call.get("model", "unknown"))
                for result in results
                for call in result.get("usageLedger", [])
            }
        ),
    }
    # Every summary revision is immutable; completed episodes are reused without paid calls.
    revision = len(list(output.glob("summary-*.json"))) + 1
    freeze(output / f"summary-{revision:03}.json", report)
    from learnloop.evaluation.report import markdown

    (output / f"summary-{revision:03}.md").write_text(markdown(report), encoding="utf-8")
    return report
