"""Python API for local SQLite-backed experiments; no listening HTTP server."""

import os
import secrets
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from learnloop.api import create_app
from learnloop.core.config import Settings
from learnloop.persistence.database import session_factory
from learnloop.runtime.worker import work_once
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from . import BACKEND
from .prompts import PromptStore
from .services import LabServices

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def load_settings(root):
    root = Path(root).resolve()
    file = root / ".env"
    values = dotenv_values(file) if file.exists() else {}
    url = make_url(
        os.environ.get("DATABASE_URL")
        or values.get("DATABASE_URL")
        or "sqlite:///data/workspace.db"
    )
    if url.drivername != "sqlite" or url.database in (None, "", ":memory:"):
        raise ValueError("Agent lab requires a file-backed sqlite:/// database URL.")
    database = Path(url.database)
    if not database.is_absolute():
        database = root / database
    database = database.resolve()
    # Experiments must not silently modify the web app's database.
    if database.is_relative_to(BACKEND.resolve()):
        raise ValueError(
            "Choose a lab database outside backend/ to keep web data separate."
        )
    url = url.set(database=str(database))
    return Settings(
        _env_file=file,
        database_url=SecretStr(url.render_as_string(hide_password=False)),
        api_token=SecretStr(secrets.token_urlsafe(32)),
    )


class Workspace:
    """Use in a with-block. Services may be injected for offline tests."""

    def __init__(self, root=DEFAULT_ROOT, *, services_type=LabServices):
        self.root = Path(root).resolve()
        self.settings = load_settings(self.root)
        self.prompts = PromptStore(self.root / "prompts")
        self.factory = session_factory(self.settings)
        self.services = services_type(self.settings, self.root, self.prompts)
        self.client = TestClient(
            create_app(self.settings, self.factory, self.services),
            headers={
                "Authorization": "Bearer " + self.settings.api_token.get_secret_value()
            },
            raise_server_exceptions=False,
        )

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, *args):
        try:
            self.client.__exit__(*args)
        finally:
            if hasattr(self.services, "close"):
                self.services.close()
            self.factory.kw["bind"].dispose()

    def initialize(self):
        config = Config(str(BACKEND / "alembic.ini"))
        with self.factory.kw["bind"].connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        return {"database": self.factory.kw["bind"].url.database, "schema": "head"}

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        data = response.json()
        if response.is_error:
            raise ValueError(
                f"HTTP {response.status_code}: {data.get('detail', 'Request failed')}"
            )
        return data

    def create_course(self, title):
        return self.request("POST", "/api/courses", json={"title": title})

    def upload(self, course_id, file):
        file = Path(file)
        if file.stat().st_size > self.settings.max_upload_bytes:
            raise ValueError("Document exceeds MAX_UPLOAD_BYTES.")
        with file.open("rb") as stream:
            return self.request(
                "POST",
                f"/api/courses/{course_id}/documents",
                files={"file": (file.name, stream)},
            )

    def state(self, course_id):
        return self.request("GET", f"/api/courses/{course_id}/learner-state")

    def call(self, role, prompt_id, context, schema):
        """Experiment with one production prompt and a validated output schema."""
        self.prompts.read(
            prompt_id
        )  # Validate the ID and current template before calling.
        if role not in {"Expert", "Tutoring", "Assessing"}:
            raise ValueError("Role must be Expert, Tutoring or Assessing.")
        return self.services.generate(
            role, self.prompts.defaults[prompt_id], context, schema
        )

    def tutor(self, course_id, concept_id=None):
        return self.request(
            "POST",
            f"/api/courses/{course_id}/sessions",
            json={
                "expectedLearnerVersion": self.state(course_id)["version"],
                "conceptId": concept_id,
            },
        )

    def session(self, session_id):
        return self.request("GET", f"/api/sessions/{session_id}")

    def answer(self, session_id, choice, reasoning=None, operation_id=None):
        session = self.session(session_id)
        activity = session["activity"]
        if not activity:
            raise ValueError("No question is ready. Process the Tutoring job first.")
        return self.request(
            "POST",
            f"/api/activities/{activity['id']}/responses",
            json={
                "operationId": operation_id or str(uuid4()),
                "expectedLearnerVersion": self.state(session["courseId"])["version"],
                "choiceId": choice,
                "reasoning": reasoning,
            },
        )

    def next(self, session_id):
        session = self.session(session_id)
        return self.request(
            "POST",
            f"/api/sessions/{session_id}/next",
            json={
                "expectedLearnerVersion": self.state(session["courseId"])["version"],
            },
        )

    def run(self, run_id):
        return self.request("GET", f"/api/agent-activity/runs/{run_id}")

    def resume(self, run_id, kind):
        run = self.run(run_id)
        return self.request(
            "POST",
            f"/api/agent-activity/runs/{run_id}/commands",
            json={
                "kind": kind,
                "operationId": str(uuid4()),
                "expectedVersion": run["recordVersion"],
            },
        )

    def work(self, agent=None, max_jobs=1):
        if max_jobs < 1:
            raise ValueError("max_jobs must be positive.")
        workflows = {
            "expert": "course_preparation",
            "tutoring": "next_activity",
            "assessing": "assessment",
        }
        workflow = workflows[agent] if agent else None
        processed = 0
        for _ in range(max_jobs):
            if not work_once(self.factory, self.services, workflow):
                break
            processed += 1
        return {
            "processedJobs": processed,
            "agent": agent or "all",
            "note": "Inspect runs for completion, pause or review status.",
        }
