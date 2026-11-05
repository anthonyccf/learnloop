"""Readable human handoff, including incomplete preparation and source blockers."""

from learnloop.evaluation.artifacts import freeze, read, thaw
from learnloop.evaluation.prepare import required_reviews
from learnloop.evaluation.schema import EXPERTS, Unit


def reviewable(bundle):
    unit = Unit.model_validate(thaw(bundle / "unit.json")["payload"])
    exams = thaw(bundle / "exams.json")["payload"]
    experts = {
        v: thaw(bundle / f"expert-{v}.json")["payload"]
        for v in EXPERTS
        if (bundle / f"expert-{v}.json").exists()
    }
    return unit, exams, experts


def packet(bundle):
    unit, exams, experts = reviewable(bundle)
    items = required_reviews(unit, exams, experts)
    screening = (
        thaw(bundle / "screening.json")["payload"] if (bundle / "screening.json").exists() else None
    )
    revision = len(list(bundle.glob("review-packet-*.json"))) + 1
    root = bundle / f"review-packet-{revision:03}"
    blockers = [
        {"path": str(p.relative_to(bundle)), **read(p)}
        for p in (bundle / "drafts").rglob("*needs-review.json")
    ]
    pending = [v for v in EXPERTS if v not in experts]
    payload = {
        "status": "pending_human_review",
        "scopeWarnings": unit.scopeWarnings,
        "missingExpertVariants": pending,
        "screeningComplete": screening is not None,
        "sourceBlockers": blockers,
        "items": [
            {"id": key, "hash": value, "decision": "pending"} for key, value in items.items()
        ],
    }
    freeze(root.with_suffix(".json"), payload)
    lines = [
        "# Evaluation human review packet — PENDING",
        "",
        "No approval is implied. A human must inspect the unit and complete pre/post bank, every Expert graph, all screening-flagged resources and the deterministic unflagged sample. Record actual findings using `record-review`. Failed/unfrozen Expert resources cannot be approved into use.",
        "",
        f"Missing frozen Expert variants: {', '.join(pending) or 'none'}. Multi-model/embedding screening present: {screening is not None}.",
        "",
        "## Source issues and scope",
        "",
    ]
    lines.extend(
        unit.scopeWarnings
        or [
            "No outside-unit prerequisite warning was found by export; human scope review is still required."
        ]
    )
    for blocker in blockers:
        lines += ["", f"- `{blocker['path']}`: {blocker.get('review', {})}"]
    lines += ["", "## Concepts", ""]
    for c in unit.graph.concepts:
        lines += [
            f"### {c.id}: {c.title}",
            c.summary,
            "Sources: " + ", ".join(s.chunkId for s in c.sources),
            "",
        ]
    lines += ["## Source passages", ""]
    for p in unit.passages:
        lines += [f"### {p.id}: {p.document}, page {p.page}", "", p.text, ""]
    for phase in ("pre", "post"):
        lines += [f"## {phase.title()}-test — private keys for review only", ""]
        for item in exams[phase]:
            q = item["question"]
            lines += [f"### {item['id']} ({item['conceptId']}, {q['difficulty']})", q["prompt"], ""]
            lines += [f"- {c['id']}: {c['text']}" for c in q["choices"]]
            lines += [
                "",
                f"Key: **{q['correctChoiceId']}**. {q['referenceAnswer']}",
                q["explanation"],
            ]
            for criterion in q["rubric"]:
                lines += [
                    f"- Rubric {criterion['id']} (weight {criterion['weight']}): {criterion['description']}; choice scores {criterion['choiceScores']}."
                ]
            lines += ["Sources: " + ", ".join(s["chunkId"] for s in q["sources"]), ""]
    lines += [
        "## Frozen Expert resources",
        "",
        "Inspect each named graph and resource in its `expert-VARIANT.json` file. Source-screening findings are in `screening.json`. A missing variant is not an approved or completed artifact.",
        "",
    ]
    for variant, artifact in experts.items():
        lines += [
            f"- {variant}: {len(artifact['materials'])} resource packs; review key `expert/{variant}/graph`."
        ]
        lines += [f"  - `expert/{variant}/{id}`" for id in artifact["materials"]]
    root.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root.with_suffix(".md")
