"""Run from agent_lab/: python -m learnloop_cli --help."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from learnloop.core import schemas
from learnloop.core.errors import ServiceError
from pydantic import BaseModel

from .prompts import PromptStore
from .workspace import DEFAULT_ROOT, Workspace


def parser():
    p = argparse.ArgumentParser(
        description="LearnLoop agent lab: SQLite, Python, no frontend/server."
    )
    p.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_ROOT,
        help="Local .env, prompts, agents.toml and data directory",
    )
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init", help="Create missing config/templates and migrate the lab database"
    )
    commands.add_parser(
        "doctor", help="Check SQLite, embeddings and generation configuration"
    )
    commands.add_parser("config", help="Show non-secret model/database settings")
    prompts = commands.add_parser("prompts").add_subparsers(
        dest="action", required=True
    )
    prompts.add_parser("list")
    prompts.add_parser(
        "export", help="Create missing editable templates without overwriting edits"
    )
    courses = commands.add_parser("courses").add_subparsers(
        dest="action", required=True
    )
    courses.add_parser("list")
    create = courses.add_parser("create")
    create.add_argument("title")
    show = courses.add_parser("show")
    show.add_argument("course_id")
    expert = commands.add_parser(
        "expert", help="Upload a PDF/text document and queue Expert preparation"
    )
    expert.add_argument("course_id")
    expert.add_argument("file", type=Path)
    tutor = commands.add_parser(
        "tutor", help="Queue Tutoring for a course (or resume its session)"
    )
    tutor.add_argument("course_id")
    tutor.add_argument("--concept-id")
    for name in ("session", "next", "end"):
        commands.add_parser(name).add_argument("session_id")
    answer = commands.add_parser("answer", help="Submit a choice and queue Assessing")
    answer.add_argument("session_id")
    answer.add_argument("choice", choices=list("abcd"))
    answer.add_argument("--reasoning")
    answer.add_argument(
        "--operation-id", help="Reuse the same ID when retrying a submission"
    )
    work = commands.add_parser(
        "work", help="Execute queued agent jobs synchronously; may incur model charges"
    )
    work.add_argument("--agent", choices=["expert", "tutoring", "assessing"])
    work.add_argument("--max-jobs", type=int, default=1)
    runs = commands.add_parser("runs")
    runs.add_argument("course_id")
    run = commands.add_parser("run")
    run.add_argument("run_id")
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("--kind", choices=["retry", "resume"], default="resume")
    call = commands.add_parser(
        "call", help="One prompt/schema experiment; no course or worker required"
    )
    call.add_argument("role", choices=["expert", "tutoring", "assessing"])
    call.add_argument("--prompt", required=True, help="Prompt ID from 'prompts list'")
    call.add_argument(
        "--schema",
        required=True,
        help="Backend Pydantic output class, e.g. SectionGraph",
    )
    call.add_argument("--context", required=True, type=Path, help="JSON object file")
    return p


def dispatch(args):
    root = args.workspace.resolve()
    store = PromptStore(root / "prompts")
    if args.command == "prompts":
        return (
            sorted(store.defaults)
            if args.action == "list"
            else {"created": store.export()}
        )
    if args.command == "init":
        root.mkdir(parents=True, exist_ok=True)
        for name in (".env", "agents.toml", ".gitignore"):
            source = DEFAULT_ROOT / (".env.example" if name == ".env" else name)
            if not (root / name).exists():
                shutil.copyfile(source, root / name)
        store.export()
    with Workspace(root) as lab:
        command = args.command
        if command == "init":
            return lab.initialize()
        if command == "doctor":
            response = lab.client.get("/health/ready")
            if response.is_error:
                print(json.dumps(response.json(), indent=2))
                raise ValueError(
                    "Readiness is degraded. Check the service statuses above."
                )
            return response.json()
        if command == "config":
            return {
                "workspace": str(root),
                "database": lab.factory.kw["bind"].url.database,
                "defaultModel": lab.settings.llm_model,
                "generationConfigured": lab.settings.generation_ready,
                "agentModelsFile": str(root / "agents.toml"),
            }
        if command == "courses":
            if args.action == "create":
                return lab.create_course(args.title)
            return lab.request(
                "GET",
                "/api/courses"
                + (f"/{args.course_id}" if args.action == "show" else ""),
            )
        if command == "expert":
            return lab.upload(args.course_id, args.file)
        if command == "tutor":
            return lab.tutor(args.course_id, args.concept_id)
        if command == "session":
            return lab.session(args.session_id)
        if command == "answer":
            return lab.answer(
                args.session_id, args.choice, args.reasoning, args.operation_id
            )
        if command == "next":
            return lab.next(args.session_id)
        if command == "end":
            return lab.request("POST", f"/api/sessions/{args.session_id}/end")
        if command == "work":
            return lab.work(args.agent, args.max_jobs)
        if command == "runs":
            return lab.request("GET", f"/api/courses/{args.course_id}/runs")
        if command == "run":
            return lab.run(args.run_id)
        if command == "resume":
            return lab.resume(args.run_id, args.kind)
        if command == "call":
            schema = getattr(schemas, args.schema, None)
            if not isinstance(schema, type) or not issubclass(schema, BaseModel):
                raise ValueError("Unknown backend Pydantic schema.")
            context = json.loads(args.context.read_text(encoding="utf-8"))
            if not isinstance(context, dict):
                raise ValueError("Context must be a JSON object.")
            return lab.call(args.role.title(), args.prompt, context, schema).model_dump(
                mode="json"
            )
    raise ValueError("Unknown command")


def main():
    args = parser().parse_args()
    try:
        result = dispatch(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Saved jobs/checkpoints remain available.", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001 - CLI boundary hides provider/SQL details.
        message = (
            error.message
            if isinstance(error, ServiceError)
            else str(error)
            if isinstance(error, (ValueError, FileNotFoundError))
            else type(error).__name__ + ": check configuration and run status."
        )
        print(f"Error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
