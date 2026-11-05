import itertools
import math
import statistics

from learnloop.evaluation.provider import usage
from learnloop.evaluation.schema import PROFILES


def macro_f1(truth, predicted):
    values = []
    for label in ("unassessed", "developing", "demonstrated", "review_due"):
        tp = sum(t == p == label for t, p in zip(truth, predicted))
        fp = sum(p == label and t != label for t, p in zip(truth, predicted))
        fn = sum(t == label and p != label for t, p in zip(truth, predicted))
        values.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return statistics.mean(values)


def episode_metrics(
    pre,
    post,
    evidence,
    hidden_labels,
    hidden_misconceptions,
    predicted_misconceptions,
    concepts,
    activities,
    calls,
    violations,
    post_target,
):
    before = statistics.mean(x["score"] for x in pre)
    after = statistics.mean(x["score"] for x in post)
    scores = {(x["conceptId"], x["difficulty"]): x["score"] for x in post}
    truth, predictions = [], []
    demonstrated, false = 0, 0
    for c in concepts:
        for level in ("basic", "intermediate", "advanced"):
            state = evidence.get(c["id"], {}).get(level, {}).get("state", "unassessed")
            predictions.append(state)
            truth.append(hidden_labels[c["id"]][level])
            if state == "demonstrated":
                demonstrated += 1
                false += scores[(c["id"], level)] < 1
    mastered = sum(
        scores[(c["id"], c.get("targetDifficulty", "intermediate"))] >= 1 for c in concepts
    )
    detected, actual = set(predicted_misconceptions), set(hidden_misconceptions)
    tp = len(detected & actual)
    ledger = usage(calls)
    return {
        "preScore": before,
        "postScore": after,
        "gain": after - before,
        "gainPerActivity": (after - before) / activities if activities else None,
        "postTestMasteredConcepts": mastered,
        "activities": activities,
        "activitiesAtVerifiedTarget": activities if after >= post_target else None,
        "stateMacroF1": macro_f1(truth, predictions),
        "difficultyStateAccuracy": sum(a == b for a, b in zip(truth, predictions)) / len(truth),
        "falseDemonstrationRate": false / demonstrated if demonstrated else None,
        "demonstratedEstimates": demonstrated,
        "misconceptionPrecision": tp / len(detected) if detected else None,
        "misconceptionRecall": tp / len(actual) if actual else None,
        "costPerMasteredConcept": ledger["costUsd"] / mastered
        if ledger["costUsd"] is not None and mastered
        else None,
        **violations,
        **ledger,
    }


def latency_by_role(calls):
    result = {}
    for role in sorted({c["role"] for c in calls}):
        values = sorted(c["latencyMs"] for c in calls if c["role"] == role)
        result[role] = {
            "calls": len(values),
            "medianMs": statistics.median(values),
            "p95Ms": values[max(0, math.ceil(len(values) * 0.95) - 1)],
        }
    return result


def analyze(results):
    completed = [r for r in results if r["status"] == "completed"]
    groups = {}
    for result in completed:
        key = result["configurationId"]
        groups.setdefault(key, []).append(result)
    numeric = (
        "preScore",
        "postScore",
        "gain",
        "gainPerActivity",
        "stateMacroF1",
        "falseDemonstrationRate",
        "inputTokens",
        "outputTokens",
        "latencyMs",
        "costUsd",
        "postTestMasteredConcepts",
        "simulationPolicyAgreement",
    )
    summaries = {
        key: {
            name: statistics.mean(vals)
            if (vals := [r["metrics"][name] for r in rows if r["metrics"].get(name) is not None])
            else None
            for name in numeric
        }
        for key, rows in groups.items()
    }
    frontier = []
    for key, item in summaries.items():
        dominated = False
        for other, candidate in summaries.items():
            if other == key:
                continue
            a = (
                item["postScore"],
                -(item["inputTokens"] + item["outputTokens"]),
                -item["latencyMs"],
            )
            b = (
                candidate["postScore"],
                -(candidate["inputTokens"] + candidate["outputTokens"]),
                -candidate["latencyMs"],
            )
            if all(y >= x for x, y in zip(a, b)) and any(y > x for x, y in zip(a, b)):
                dominated = True
        if not dominated:
            frontier.append(key)
    factorial = [r for r in completed if r["baseline"] == "adaptive"]
    cells = {tuple(r["variants"][f] for f in ("expert", "tutor", "assessor")) for r in factorial}
    expected = {
        (p, n)
        for p in PROFILES
        for n in range(max((r["repeat"] for r in factorial), default=-1) + 1)
    }
    balanced = len(cells) == 27 and all(
        {
            (r["profile"], r["repeat"])
            for r in factorial
            if tuple(r["variants"][f] for f in ("expert", "tutor", "assessor")) == cell
        }
        == expected
        for cell in cells
    )
    effects = {}
    if balanced:
        grand = statistics.mean(r["metrics"]["gain"] for r in factorial)
        factors = ("expert", "tutor", "assessor")
        for size in (1, 2, 3):
            for subset in itertools.combinations(factors, size):
                for levels in sorted({tuple(r["variants"][f] for f in subset) for r in factorial}):
                    term = 0
                    for n in range(size + 1):
                        for indices in itertools.combinations(range(size), n):
                            matched = [
                                r["metrics"]["gain"]
                                for r in factorial
                                if all(r["variants"][subset[i]] == levels[i] for i in indices)
                            ]
                            term += (-1) ** (size - n) * statistics.mean(matched)
                    effects["|".join(f"{f}={v}" for f, v in zip(subset, levels))] = term
        effects["grandMeanGain"] = grand
    return {
        "completed": len(completed),
        "failedOrStopped": len(results) - len(completed),
        "configurationMeans": summaries,
        "paretoByQualityTokensLatency": sorted(frontier),
        "balanced27Cells": balanced,
        "gainFactorialEffects": effects,
        "effectsInterpretation": "Balanced descriptive contrasts, not causal significance tests or human learning effects.",
    }
