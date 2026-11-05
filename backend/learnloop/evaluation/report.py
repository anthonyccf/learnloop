def markdown(report):
    title = (
        "Workflow verification — not research evidence"
        if report["mode"] == "workflow_only"
        else "Controlled pseudo-student evaluation"
    )
    lines = [
        f"# {title}",
        "",
        f"Completed episodes: {report['completed']}. Failed/stopped: {report['failedOrStopped']}.",
        "",
        "Scores describe the configured simulation and held-out MCQs. They do not establish human learning gains. Preparation usage is reported separately; unavailable provider cost is unknown, never zero.",
        "",
        "| Configuration | Pre | Post | Gain | State macro F1 | Tokens | Cost USD |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in sorted(report["configurationMeans"].items()):
        cost = "unknown" if item["costUsd"] is None else f"{item['costUsd']:.6f}"
        lines.append(
            f"| {name} | {item['preScore']:.3f} | {item['postScore']:.3f} | {item['gain']:.3f} | {item['stateMacroF1']:.3f} | {item['inputTokens'] + item['outputTokens']:.0f} | {cost} |"
        )
    lines += [
        "",
        f"Balanced complete 27-cell factorial: {report['balanced27Cells']}.",
        "",
        "Pareto frontier (post-test quality, tokens and latency): "
        + ", ".join(report["paretoByQualityTokensLatency"]),
        "",
        "Main, pairwise and three-way descriptive gain contrasts are in the JSON summary only when every cell has the same four profiles and repeat IDs. No significance or generalisation claim is implied.",
        "",
        "Failed/budget-exhausted episodes are excluded from score means and remain visible in the JSON results. Attrition must be reviewed before interpreting comparisons. Activities-at-verified-target is endpoint-censored, not the earliest possible mastery time.",
    ]
    return "\n".join(lines) + "\n"
