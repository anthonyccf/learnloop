import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from learnloop.core.schemas import Graph
from learnloop.evaluation.artifacts import digest, freeze, thaw, write
from learnloop.evaluation.experiment import run_matrix
from learnloop.evaluation.fixtures import FixtureProvider, prepare_fixture
from learnloop.evaluation.prepare import (
    author_exams,
    build_expert,
    load_bundle,
    required_reviews,
    screen,
)
from learnloop.evaluation.provider import Provider
from learnloop.evaluation.schema import ASSESSORS, EXPERTS, TUTORS, ExperimentConfig, Unit


def export_unit(document_id, offset, count, destination, release_id=None):
    # Only this explicit import command touches SQL; the transaction is read-only.
    from types import SimpleNamespace

    from sqlalchemy import text

    from learnloop.persistence.database import Document, session_factory
    from learnloop.persistence.releases import get_release

    with session_factory()() as db:
        if db.bind.dialect.name != "sqlite":
            db.execute(text("SET TRANSACTION READ ONLY"))
        doc = db.get(Document, document_id)
        if not doc:
            raise ValueError("Choose a source document in a complete release")
        release = get_release(db, doc.course_id, release_id)
        if not release:
            raise ValueError("Publish a complete course release before exporting a research unit")
        saved = next((d for d in release.payload["documents"] if d["id"] == document_id), None)
        if not saved:
            raise ValueError("The selected document is not included in this release")
        doc = SimpleNamespace(**saved)
        originals = doc.graph["concepts"][offset : offset + count]
        mapping = {c["id"]: f"c{i + 1:02}" for i, c in enumerate(originals)}
        edges_in_release = []
        for edge in release.payload["graph"]["prerequisites"]:
            source = edge.get("source")
            if source is None:
                chunk_id = edge["sourceChunkIds"][0]
                source = {
                    "chunkId": chunk_id,
                    "quote": release.payload["chunks"][chunk_id]["text"][:200],
                }
            edges_in_release.append(
                {
                    "prerequisite": edge["prerequisite"],
                    "dependent": edge["dependent"],
                    "source": source,
                }
            )
        source_ids = {s["chunkId"] for c in originals for s in c["sources"]}
        source_ids.update(
            e["source"]["chunkId"]
            for e in edges_in_release
            if e["dependent"] in mapping and e["prerequisite"] in mapping
        )
        chunks = [
            SimpleNamespace(**c)
            for id, c in sorted(release.payload["chunks"].items())
            if id in source_ids
        ]
        passages = {c.id: f"p{i + 1:02}" for i, c in enumerate(chunks)}
        concepts = [
            {
                **{k: c[k] for k in ("title", "summary")},
                "id": mapping[c["id"]],
                "targetDifficulty": "intermediate",
                "sources": [{**s, "chunkId": passages[s["chunkId"]]} for s in c["sources"]],
            }
            for c in originals
        ]
        edges = []
        warnings = []
        for edge in edges_in_release:
            if edge["dependent"] in mapping:
                if edge["prerequisite"] not in mapping:
                    warnings.append(
                        "Outside-unit prerequisite requires scope review: " + edge["prerequisite"]
                    )
                elif edge["source"]["chunkId"] in passages:
                    edges.append(
                        {
                            **edge,
                            "prerequisite": mapping[edge["prerequisite"]],
                            "dependent": mapping[edge["dependent"]],
                            "source": {
                                **edge["source"],
                                "chunkId": passages[edge["source"]["chunkId"]],
                            },
                        }
                    )
        unit = Unit(
            id="comp7608b-unit-" + doc.id[:8],
            title="COMP7608B: controlled inference course unit",
            sourceSha256=doc.sha256,
            passages=[
                {"id": passages[c.id], "text": c.text, "page": c.page, "document": c.label}
                for c in chunks
            ],
            graph=Graph(concepts=concepts, prerequisites=edges),
            scopeWarnings=warnings,
        )
    result = freeze(destination / "unit.json", unit.model_dump())
    freeze(
        destination / "release-provenance.json",
        {
            "releaseId": release.id,
            "releaseHash": release.sha256,
            "releaseVersion": release.version,
            "courseId": release.course_id,
            "unitHash": result["sha256"],
        },
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="File-isolated LearnLoop evaluation. Offline results are workflow checks, not research."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser(
        "status", help="Check research readiness without credentials or model calls"
    )
    status.add_argument("--bundle", type=Path, required=True)
    status.add_argument(
        "--model", help="Optional intended study model; checked against frozen Experts"
    )
    status.add_argument("--temperature", type=float, default=0.2)
    pilot = sub.add_parser("canary")
    pilot.add_argument("--bundle", type=Path, required=True)
    pilot.add_argument("--output", type=Path, required=True)
    export = sub.add_parser("export-unit")
    export.add_argument("--document", required=True)
    export.add_argument(
        "--release", help="Pin a specific course release; defaults to the latest complete release"
    )
    export.add_argument("--offset", type=int, default=11)
    export.add_argument("--count", type=int, default=12)
    export.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--bundle", type=Path, required=True)
    prepare.add_argument("--offline", action="store_true")
    prepare.add_argument("--stage", choices=["exams", *EXPERTS, "all"], default="all")
    prepare.add_argument("--max-tokens", type=int, default=1500000)
    prepare.add_argument("--workers", type=int, choices=[1, 2, 3], default=1)
    screening = sub.add_parser("screen")
    screening.add_argument("--bundle", type=Path, required=True)
    screening.add_argument("--models", nargs="+", required=True)
    packet = sub.add_parser("review-packet")
    packet.add_argument("--bundle", type=Path, required=True)
    review = sub.add_parser("record-review")
    review.add_argument("--bundle", type=Path, required=True)
    review.add_argument("--item", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--notes", required=True)
    review.add_argument("--decision", choices=["approved", "rejected"], required=True)
    run = sub.add_parser("run")
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--offline", action="store_true")
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--activities", type=int, default=24)
    run.add_argument("--seed", type=int, default=72)
    run.add_argument("--session-gap-days", type=int, default=8)
    run.add_argument("--max-calls", type=int, default=256)
    run.add_argument("--max-tokens", type=int, default=150000)
    run.add_argument("--selected", nargs=3, metavar=("EXPERT", "TUTOR", "ASSESSOR"))
    run.add_argument("--baselines", action="store_true")
    run.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        from learnloop.evaluation.readiness import readiness

        result = readiness(args.bundle, model=args.model, temperature=args.temperature)
        print(json.dumps(result, indent=2))
        if not result["ready"]:
            raise SystemExit(1)
        return
    if args.command == "export-unit":
        export_unit(args.document, args.offset, args.count, args.output, args.release)
        print("Draft unit exported read-only. Human scope/content review is pending.")
        return
    if args.command == "prepare" and args.offline:
        unit = Unit.model_validate(thaw(args.bundle / "unit.json")["payload"])
        # Unit already exists; fixture builder writes only the remaining files.
        temporary = args.bundle / "offline-fixtures"
        prepare_fixture(unit, temporary)
        print("Workflow fixtures prepared at " + str(temporary))
        return
    if args.command in ("review-packet", "record-review"):
        from learnloop.evaluation.review import packet, reviewable

        unit, exams, artifacts = reviewable(args.bundle)
        items = required_reviews(unit, exams, artifacts)
        if args.command == "review-packet":
            print("Human review packet created; no approvals recorded: " + str(packet(args.bundle)))
        else:
            if args.item not in items or not args.reviewer.strip() or not args.notes.strip():
                raise ValueError(
                    "A known item, human reviewer identity and substantive review notes are required"
                )
            previous = (
                thaw(args.bundle / "reviews.json")["payload"]
                if (args.bundle / "reviews.json").exists()
                else {}
            )
            previous[args.item] = {
                "hash": items[args.item],
                "decision": args.decision,
                "reviewer": args.reviewer,
                "notes": args.notes,
                "at": datetime.now(UTC).isoformat(),
                "provenance": "human-asserted CLI review",
            }
            from learnloop.evaluation.artifacts import checkpoint

            checkpoint(
                args.bundle / "reviews.json", {"sha256": digest(previous), "payload": previous}
            )
            write(
                args.bundle / "review-history" / f"{uuid4().hex}.json",
                previous[args.item] | {"item": args.item},
            )
        return
    settings = None
    if not getattr(args, "offline", False):
        from learnloop.core.config import get_settings

        settings = get_settings()
    if args.command == "canary":
        from learnloop.evaluation.canary import canary

        unit = Unit.model_validate(thaw(args.bundle / "unit.json")["payload"])
        result = canary(
            unit,
            Provider(settings, args.output / "preparation-calls", max_calls=16, max_tokens=150000),
            Provider(settings, args.output / "episode" / "calls", max_calls=32, max_tokens=150000),
            args.output,
        )
        print(
            json.dumps(
                {"mode": "canary", "status": result["status"], "metrics": result.get("metrics")}
            )
        )
    elif args.command == "prepare":
        unit = Unit.model_validate(thaw(args.bundle / "unit.json")["payload"])

        def provider(stage):
            stage_root = args.bundle / "preparation-calls" / stage
            if stage_root.exists() and len(list(stage_root.iterdir())) >= 3:
                raise ValueError(
                    "Three-attempt preparation limit reached; inspect retained drafts and source issues"
                )
            return Provider(
                settings,
                stage_root / uuid4().hex,
                max_calls=200,
                max_tokens=args.max_tokens,
            )

        if args.stage in ("exams", "all") and not (args.bundle / "exams.json").exists():
            author_exams(unit, provider("exams"), args.bundle / "exams.json")
        if args.stage != "exams":
            exams = thaw(args.bundle / "exams.json")["payload"]
            for variant in EXPERTS if args.stage == "all" else [args.stage]:
                if not (args.bundle / f"expert-{variant}.json").exists():
                    build_expert(
                        unit,
                        exams,
                        variant,
                        provider(variant),
                        args.bundle / f"expert-{variant}.json",
                        workers=args.workers,
                    )
        print("Completed artifacts are frozen. Screening and human review remain required.")
    elif args.command == "screen":
        from learnloop.services.clients import Services

        unit, _, artifacts = load_bundle(args.bundle)
        providers = [
            Provider(
                settings,
                args.bundle / "screening-calls" / uuid4().hex,
                model=model,
                max_calls=200,
                max_tokens=1500000,
            )
            for model in args.models
        ]
        freeze(
            args.bundle / "screening.json",
            screen(
                unit,
                artifacts,
                providers,
                Services(settings).embed,
                settings.ollama_embedding_model,
                args.bundle / "screening-cache",
            ),
        )
        print("Screened without recording human approval.")
    elif args.command == "run":
        model = "workflow-fixture" if args.offline else settings.llm_model
        config = ExperimentConfig(
            seed=args.seed,
            repeats=args.repeats,
            activities=args.activities,
            sessionGapDays=args.session_gap_days,
            maxCalls=args.max_calls,
            maxTokens=args.max_tokens,
            model=model,
        )
        selected = None
        if args.selected:
            if not (
                args.selected[0] in EXPERTS
                and args.selected[1] in TUTORS
                and args.selected[2] in ASSESSORS
            ):
                raise ValueError("Unknown selected configuration")
            selected = dict(zip(("expert", "tutor", "assessor"), args.selected))
        factory = (
            (lambda _: FixtureProvider())
            if args.offline
            else (
                lambda path: Provider(
                    settings,
                    path,
                    seed=args.seed,
                    temperature=config.temperature,
                    max_calls=args.max_calls,
                    max_tokens=args.max_tokens,
                )
            )
        )
        report = run_matrix(
            args.bundle,
            args.output,
            config,
            factory,
            offline=args.offline,
            selected=selected,
            baselines=args.baselines,
            retry_failed=args.retry_failed,
        )
        print(
            json.dumps(
                {k: report[k] for k in ("mode", "completed", "failedOrStopped", "balanced27Cells")}
            )
        )


if __name__ == "__main__":
    main()
