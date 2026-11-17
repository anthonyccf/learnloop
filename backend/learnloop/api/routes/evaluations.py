"""Local, file-isolated controls for the controlled evaluation harness."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from learnloop.evaluation.artifacts import digest, freeze, thaw
from learnloop.evaluation.readiness import readiness
from learnloop.evaluation.simulator import PROFILES
from learnloop.persistence.database import AgentTemplate, Course, Document
from learnloop.persistence.releases import get_release
from learnloop.pseudo_progress import progress
from learnloop.pseudo_retry import inputs as retry_inputs

BACKEND = Path(__file__).resolve().parents[3]
BUNDLE_ID = "comp7608b-inference-v2-draft"
BUNDLE = BACKEND / "evaluation" / BUNDLE_ID
RUNS = BACKEND / "data" / "evaluation-workbench"


class StartEvaluation(BaseModel):
    bundle: Literal["comp7608b-inference-v2-draft"]
    expert: Literal["structural", "grounded", "verified"] = "grounded"
    tutor: Literal["state", "graph", "utility"] = "utility"
    assessor: Literal["correctness", "weighted", "conservative"] = "weighted"
    repeats: int = Field(default=2, ge=1, le=10)
    activities: int = Field(default=6, ge=2, le=100)
    maxCalls: int = Field(default=256, ge=1, le=10000)
    maxTokens: int = Field(default=150000, ge=1000, le=10000000)
    baselines: bool = False


class SaveSetup(BaseModel):
    courseId: str
    documentId: str
    expertTemplateId: str | None = None
    tutorTemplateId: str | None = None
    assessingTemplateId: str | None = None
    learnerProfileIds: list[str] = Field(
        default_factory=lambda: list(PROFILES), min_length=1, max_length=20
    )


class LearnerProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model: str = Field(default="configured", min_length=1, max_length=200)
    basic: float = Field(ge=0, le=1, allow_inf_nan=False)
    intermediate: float = Field(ge=0, le=1, allow_inf_nan=False)
    advanced: float = Field(ge=0, le=1, allow_inf_nan=False)
    hint: float = Field(ge=0, le=1, allow_inf_nan=False)
    gain: float = Field(ge=0, le=0.15, allow_inf_nan=False)
    delaySeconds: int = Field(ge=1, le=3600)
    misconceptions: bool = False

    @field_validator("name", "model")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()


class StartPseudoRun(BaseModel):
    setupId: str = Field(pattern=r"^[a-f0-9]{32}$")
    concepts: int = Field(default=1, ge=1, le=20)
    activities: int = Field(default=2, ge=2, le=12)
    baselines: bool = False
    sourceRunId: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class RetryPseudoEpisode(BaseModel):
    learnerId: str = Field(min_length=1, max_length=100)
    condition: Literal["adaptive", "fixed_sequence", "memory_free"] = "adaptive"


def _root(owner):
    return RUNS / hashlib.sha256(owner.encode()).hexdigest()


def _setup_root(owner):
    return RUNS / "setups" / hashlib.sha256(owner.encode()).hexdigest()[:24]


def _learner_root(owner):
    return RUNS / "learners" / hashlib.sha256(owner.encode()).hexdigest()[:24]


def _pseudo_root(owner):
    return BACKEND / "data" / "pseudo-runs" / hashlib.sha256(owner.encode()).hexdigest()[:16]


def _pseudo_view(path):
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    saved = (
        thaw(path / "input.json")["payload"]["setup"] if (path / "input.json").is_file() else None
    )
    if "materialId" not in job and saved:
        job["materialId"] = saved["material"]["id"]
        job["releaseId"] = saved["release"]["id"]
    job["preparedAvailable"] = all(
        (path / name).is_file() for name in ("unit.json", "exams.json", "expert.json")
    )
    status = (
        json.loads((path / "status.json").read_text(encoding="utf-8"))
        if (path / "status.json").exists()
        else {"status": "starting"}
    )
    report = None
    if (path / "report.json").exists():
        raw = thaw(path / "report.json")["payload"]
        report = {
            k: raw[k]
            for k in (
                "mode",
                "conceptCount",
                "scopeWarnings",
                "preparationUsage",
                "completed",
                "failedOrStopped",
                "configurationMeans",
            )
        }
        report["episodes"] = [
            {
                k: r.get(k)
                for k in (
                    "learnerName",
                    "baseline",
                    "status",
                    "errorType",
                    "metrics",
                    "profileControlValid",
                )
            }
            for r in raw["results"]
        ]
    return {
        **job,
        **status,
        "report": report,
        "progress": progress(path, saved, job, status["status"]) if saved else [],
    }


def _builtin_profiles():
    names = {
        "novice": "Novice",
        "intermediate": "Intermediate",
        "misconception_prone": "Misconception-prone",
        "hint_dependent": "Hint-dependent",
    }
    return [
        {
            "id": key,
            "name": names[key],
            "model": "configured",
            "basic": value["ability"][0],
            "intermediate": value["ability"][1],
            "advanced": value["ability"][2],
            "hint": value["hint"],
            "gain": value["gain"],
            "delaySeconds": value["delay"] // 1000,
            "misconceptions": value["misconceptions"],
            "builtin": True,
        }
        for key, value in PROFILES.items()
    ]


def _learners(owner):
    return _builtin_profiles() + [
        thaw(path)["payload"] for path in _learner_root(owner).glob("*.json")
    ]


def _view(path):
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    status_path = path / "status.json"
    status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else {"status": "starting"}
    )
    result_paths = list((path / "output" / "episodes").glob("*/attempt-*/result.json"))
    summaries = sorted((path / "output").glob("summary-*.json"))
    summary = None
    if summaries:
        report = thaw(summaries[-1])["payload"]
        summary = {
            key: report[key]
            for key in ("mode", "completed", "failedOrStopped", "configurationMeans")
        }
    return {**job, **status, "episodesFinished": len(result_paths), "summary": summary}


def build_router(context):
    router = APIRouter(tags=["Evaluation"])

    @router.get("/api/evaluations/bundles")
    def bundles(principal=Depends(context.owner)):
        del principal
        status = readiness(BUNDLE, model=context.settings.llm_model)
        return [{"id": BUNDLE_ID, "title": "COMP7608B — Inference", "readiness": status}]

    @router.get("/api/evaluations/runs")
    def list_runs(principal=Depends(context.owner)):
        root = _root(principal)
        return [
            _view(p) for p in sorted(root.glob("*"), reverse=True) if (p / "job.json").is_file()
        ]

    @router.get("/api/evaluations/setups")
    def list_setups(principal=Depends(context.owner)):
        setups = _setup_root(principal)
        return [thaw(path)["payload"] for path in setups.glob("*.json")]

    @router.get("/api/evaluations/learners")
    def list_learners(principal=Depends(context.owner)):
        return _learners(principal)

    @router.post("/api/evaluations/learners", status_code=201)
    def create_learner(request: LearnerProfileInput, principal=Depends(context.owner)):
        profile = {"id": uuid4().hex, **request.model_dump(), "builtin": False}
        freeze(_learner_root(principal) / f"{profile['id']}.json", profile)
        return profile

    @router.post("/api/evaluations/setups", status_code=201)
    def save_setup(request: SaveSetup, principal=Depends(context.owner)):
        profiles = {item["id"]: item for item in _learners(principal)}
        if len(set(request.learnerProfileIds)) != len(request.learnerProfileIds) or any(
            id not in profiles for id in request.learnerProfileIds
        ):
            raise HTTPException(422, "Choose available learner profiles without duplicates.")
        with context.factory() as db:
            course = context.owned(db, Course, request.courseId, principal)
            release = get_release(db, course.id)
            if not release:
                raise HTTPException(
                    409, "Prepare and publish this course before saving a test setup."
                )
            if request.documentId == "__all__":
                documents = release.payload["documents"]
                if not documents:
                    raise HTTPException(409, "The published course has no materials.")
                material = {
                    "id": "__all__",
                    "filename": "All published materials",
                    "documentCount": len(documents),
                    "sha256": digest(sorted((d["id"], d["sha256"]) for d in documents)),
                }
            else:
                document = context.owned(db, Document, request.documentId, principal)
                if document.course_id != course.id:
                    raise HTTPException(422, "The material does not belong to the selected course.")
                source = next(
                    (d for d in release.payload["documents"] if d["id"] == document.id), None
                )
                if not source:
                    raise HTTPException(
                        409, "The selected material is not in the current published course release."
                    )
                material = {
                    "id": document.id,
                    "filename": source["filename"],
                    "sha256": source["sha256"],
                }
            templates = {}
            for agent, template_id in (
                ("expert", request.expertTemplateId),
                ("tutor", request.tutorTemplateId),
                ("assessing", request.assessingTemplateId),
            ):
                if template_id is None:
                    templates[agent] = None
                    continue
                template = db.get(AgentTemplate, template_id)
                if not template or template.owner_id != principal or template.agent != agent:
                    raise HTTPException(404, "Selected agent template not found.")
                templates[agent] = template.data
            setup_id = uuid4().hex
            setup = {
                "id": setup_id,
                "createdAt": datetime.now(UTC).isoformat(),
                "course": {"id": course.id, "title": course.title},
                "material": material,
                "release": {"id": release.id, "version": release.version, "sha256": release.sha256},
                "templates": templates,
                "learners": [profiles[id] for id in request.learnerProfileIds],
                "status": "configuration_saved",
            }
        freeze(_setup_root(principal) / f"{setup_id}.json", setup)
        return setup

    @router.get("/api/evaluations/pseudo-runs")
    def list_pseudo_runs(principal=Depends(context.owner)):
        return [
            _pseudo_view(path)
            for path in _pseudo_root(principal).glob("*")
            if (path / "job.json").is_file()
        ]

    @router.post("/api/evaluations/pseudo-runs", status_code=202)
    def start_pseudo_run(request: StartPseudoRun, principal=Depends(context.owner)):
        setup_path = _setup_root(principal) / f"{request.setupId}.json"
        if not setup_path.is_file():
            raise HTTPException(404, "Saved setup not found.")
        setup = thaw(setup_path)["payload"]
        if not setup.get("learners"):
            raise HTTPException(
                409, "This older setup has no learner profiles. Save a new setup first."
            )
        if not context.settings.generation_ready:
            raise HTTPException(409, "Model generation is not configured on the backend.")
        with context.factory() as db:
            context.owned(db, Course, setup["course"]["id"], principal)
            release = get_release(db, setup["course"]["id"], setup["release"]["id"])
            if not release or release.sha256 != setup["release"]["sha256"]:
                raise HTTPException(409, "The saved course release is unavailable or changed.")
            sources = (
                release.payload["documents"]
                if setup["material"]["id"] == "__all__"
                else [d for d in release.payload["documents"] if d["id"] == setup["material"]["id"]]
            )
            if not sources or any(not d["graph"].get("concepts") for d in sources):
                raise HTTPException(
                    409, "Each selected material needs published concepts before it can be tested."
                )
            if (
                setup["material"]["id"] == "__all__"
                and not request.sourceRunId
                and request.concepts < len(sources)
            ):
                raise HTTPException(
                    422, f"Choose at least {len(sources)} concepts to include every material."
                )
            release_payload = release.payload
        reused = None
        if request.sourceRunId:
            source_path = _pseudo_root(principal) / request.sourceRunId
            required = ("input.json", "unit.json", "exams.json", "expert.json")
            if not all((source_path / name).is_file() for name in required):
                raise HTTPException(409, "The selected run has no complete prepared materials.")
            original = thaw(source_path / "input.json")["payload"]["setup"]
            if (
                original["material"]["id"] != setup["material"]["id"]
                or original["material"]["sha256"] != setup["material"]["sha256"]
                or original["release"]["sha256"] != setup["release"]["sha256"]
                or original["release"]["id"] != setup["release"]["id"]
            ):
                raise HTTPException(
                    409, "Choose a run from the same material and published course version."
                )
            reused = {
                "unit": thaw(source_path / "unit.json")["payload"],
                "exams": thaw(source_path / "exams.json")["payload"],
                "expert": thaw(source_path / "expert.json")["payload"],
            }
        if not reused and setup["material"]["id"] == "__all__":
            from learnloop.pseudo_experiment import make_unit

            try:
                make_unit(setup, release_payload, request.concepts)
            except (ValueError, KeyError):
                raise HTTPException(
                    409,
                    "The selected concepts do not cover every published material. Increase the concept limit or select one material.",
                ) from None
        run_id = uuid4().hex
        path = _pseudo_root(principal) / run_id
        path.mkdir(parents=True)
        job = {
            "id": run_id,
            "createdAt": datetime.now(UTC).isoformat(),
            "setupId": request.setupId,
            "course": setup["course"]["title"],
            "material": setup["material"]["filename"],
            "materialId": setup["material"]["id"],
            "releaseId": setup["release"]["id"],
            "config": request.model_dump(),
            "learnerCount": len(setup["learners"]),
            "mode": "exploratory",
        }
        (path / "job.json").write_text(json.dumps(job), encoding="utf-8")
        freeze(path / "input.json", {"setup": setup, "release": release_payload, "reused": reused})
        try:
            subprocess.Popen(
                [sys.executable, "-m", "learnloop.pseudo_experiment_job", str(path)],
                cwd=BACKEND,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt",
            )
        except OSError:
            (path / "status.json").write_text(
                '{"status":"failed","message":"Could not start evaluation process."}',
                encoding="utf-8",
            )
            raise HTTPException(503, "Could not start evaluation process.") from None
        return _pseudo_view(path)

    @router.post("/api/evaluations/pseudo-runs/{run_id}/retry", status_code=202)
    def retry_pseudo_episode(
        run_id: str, request: RetryPseudoEpisode, principal=Depends(context.owner)
    ):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise HTTPException(404, "Test run not found.")
        path = _pseudo_root(principal) / run_id
        if not (path / "job.json").is_file() or not (path / "report.json").is_file():
            raise HTTPException(409, "Wait for the original run to finish before retrying.")
        status = json.loads((path / "status.json").read_text(encoding="utf-8"))
        if status.get("status") not in ("completed", "completed_with_failures"):
            raise HTTPException(409, "Wait for the original run to finish before retrying.")
        job = json.loads((path / "job.json").read_text(encoding="utf-8"))
        if request.condition != "adaptive" and not job["config"].get("baselines"):
            raise HTTPException(404, "Episode not found.")
        setup = thaw(path / "input.json")["payload"]["setup"]
        if not any(item["id"] == request.learnerId for item in setup.get("learners", [])):
            raise HTTPException(404, "Episode not found.")
        root = path / "episodes" / digest([request.learnerId, request.condition])[:16]
        if not (root / "result.json").is_file():
            raise HTTPException(409, "There is no finished episode to retry.")
        lock = root / "retry.lock"
        try:
            lock.touch(exist_ok=False)
        except FileExistsError:
            raise HTTPException(409, "A retry for this learner is already running.") from None
        try:
            attempts = sorted((root / "retries").glob("attempt-*"))
            if len(attempts) >= 2:
                raise HTTPException(409, "This episode has reached its three-attempt limit.")
            latest = attempts[-1] if attempts else root
            if not (latest / "result.json").is_file():
                raise HTTPException(
                    409, "The previous retry did not finish; inspect its local artifacts."
                )
            previous = thaw(latest / "result.json")["payload"]
            if previous.get("status") not in ("failed", "budget_exhausted", "simulation_invalid"):
                raise HTTPException(409, "Only failed or budget-stopped episodes can be retried.")
            if not context.settings.generation_ready:
                raise HTTPException(409, "Model generation is not configured on the backend.")
            try:
                retry_inputs(path, request.learnerId, request.condition, context.settings)
            except (ValueError, KeyError, OSError):
                raise HTTPException(
                    409,
                    "The original model, evaluation code or frozen inputs changed; start a new test instead.",
                ) from None
            name = f"attempt-{len(attempts) + 1:02}"
            destination = root / "retries" / name
            destination.mkdir(parents=True)
            (destination / "retry-status.json").write_text(
                '{"status":"starting"}', encoding="utf-8"
            )
            try:
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "learnloop.pseudo_retry_job",
                        str(path),
                        request.learnerId,
                        request.condition,
                        name,
                    ],
                    cwd=BACKEND,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    start_new_session=os.name != "nt",
                )
            except OSError:
                freeze(
                    destination / "result.json",
                    {"status": "failed", "errorType": "ProcessLaunchError"},
                )
                raise HTTPException(503, "Could not start the retry.") from None
        except Exception:
            lock.unlink(missing_ok=True)
            raise
        return {"status": "starting", "attempt": len(attempts) + 2}

    @router.get("/api/evaluations/runs/{run_id}")
    def get_run(run_id: str, principal=Depends(context.owner)):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise HTTPException(404, "Evaluation not found.")
        path = _root(principal) / run_id
        if not (path / "job.json").is_file():
            raise HTTPException(404, "Evaluation not found.")
        return _view(path)

    @router.post("/api/evaluations/runs", status_code=202)
    def start_run(request: StartEvaluation, principal=Depends(context.owner)):
        check = readiness(BUNDLE, model=context.settings.llm_model)
        if not check["ready"]:
            raise HTTPException(
                409,
                "The evaluation bundle is not ready. Complete its review and resolve all readiness blockers.",
            )
        if not context.settings.generation_ready:
            raise HTTPException(409, "Model generation is not configured on the backend.")
        run_id = uuid4().hex
        path = _root(principal) / run_id
        path.mkdir(parents=True)
        job = {
            "id": run_id,
            "createdAt": datetime.now(UTC).isoformat(),
            "settings": request.model_dump(),
            "model": context.settings.llm_model,
        }
        (path / "job.json").write_text(json.dumps(job), encoding="utf-8")
        try:
            subprocess.Popen(
                [sys.executable, "-m", "learnloop.evaluation_workbench_job", str(path)],
                cwd=BACKEND,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt",
            )
        except OSError:
            (path / "status.json").write_text(
                '{"status":"failed","message":"Could not start the evaluation process."}',
                encoding="utf-8",
            )
            raise HTTPException(503, "Could not start the evaluation process.") from None
        return _view(path)

    return router
