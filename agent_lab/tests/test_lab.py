"""Offline integration checks: real workflows, fake model/embedding responses."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from learnloop.core.errors import ServiceError
from learnloop.core.schemas import TutorChatReply
from learnloop_cli import BACKEND, Workspace
from learnloop_cli.__main__ import main
from learnloop_cli.prompts import PromptStore
from learnloop_cli.services import GenerationClient
from learnloop_cli.workspace import load_settings

spec = importlib.util.spec_from_file_location(
    "backend_lab_fakes", BACKEND / "tests/conftest.py"
)
fakes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fakes)


class FakeServices(fakes.FakeServices):
    def __init__(self, settings, root, prompts):
        super().__init__(settings)


@pytest.fixture
def root(tmp_path, monkeypatch):
    # Never inherit a developer's model key or database during offline tests.
    for key in ("DATABASE_URL", "OPENROUTER_API_KEY", "LOCAL_OWNER_ID"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=offline-test\n", encoding="utf-8"
    )
    return tmp_path


def test_isolated_settings_and_migrations(root):
    with Workspace(root) as lab:
        lab.initialize()
        lab.initialize()  # Existing databases upgrade without losing records.
        course = lab.create_course("Retained course")
    with Workspace(root) as lab:
        lab.initialize()
        assert lab.request("GET", "/api/courses")[0]["id"] == course["id"]
        assert Path(lab.factory.kw["bind"].url.database) == root / "data/workspace.db"


def test_rejects_backend_database_and_non_sqlite(root, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "sqlite:///" + (BACKEND / "data/learnloop.db").as_posix()
    )
    with pytest.raises(ValueError, match="outside backend"):
        load_settings(root)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/example")
    with pytest.raises(ValueError, match="file-backed"):
        load_settings(root)


def test_prompt_suffix_and_non_destructive_export(root):
    store = PromptStore(root / "prompts")
    store.export()
    name = "expert/curriculum_prompt"
    original = store.defaults[name]
    path = root / "prompts" / f"{name}.txt"
    path.write_text("My edited curriculum instruction.", encoding="utf-8")
    store.export()
    assert store.resolve(original + "\nIndependent reviewer suffix.") == (
        name,
        "My edited curriculum instruction.\nIndependent reviewer suffix.",
    )


def test_role_model_prompt_and_trace(root, monkeypatch):
    (root / "agents.toml").write_text(
        '[tutoring]\nmodel = "test/custom-model"\n', encoding="utf-8"
    )
    store = PromptStore(root / "prompts")
    store.export()
    (root / "prompts/tutoring_chat/chat_prompt.txt").write_text(
        "Custom coaching instruction.", encoding="utf-8"
    )
    calls = []

    def generate(self, role, instruction, context, schema):
        calls.append((self.settings.llm_model, role, instruction, context))
        return schema(text="A useful explanation.")

    monkeypatch.setattr(GenerationClient, "generate", generate)
    with Workspace(root) as lab:
        reply = lab.call(
            "Tutoring", "tutoring_chat/chat_prompt", {"message": "Help"}, TutorChatReply
        )
    assert reply.text == "A useful explanation."
    assert calls[0][:3] == (
        "test/custom-model",
        "Tutoring",
        "Custom coaching instruction.",
    )
    trace = json.loads(next((root / "data/traces").glob("*.json")).read_text())
    assert trace["promptId"] == "tutoring_chat/chat_prompt"
    assert trace["output"]["text"] == reply.text
    assert "offline-test" not in json.dumps(trace)


def test_complete_three_agent_flow(root):
    document = root / "course.txt"
    document.write_text(fakes.COURSE_TEXT, encoding="utf-8")
    with Workspace(root, services_type=FakeServices) as lab:
        lab.initialize()
        course = lab.create_course("Gradient descent")
        upload = lab.upload(course["id"], document)
        assert lab.work("expert")["processedJobs"] == 1
        assert lab.run(upload["runId"])["status"] == "completed"
        session = lab.tutor(course["id"])
        assert lab.work("tutoring")["processedJobs"] == 1
        session = lab.session(session["id"])
        assert session["activity"]["prompt"]
        assert "correctChoiceId" not in session["activity"]
        receipt = lab.answer(session["id"], "a", operation_id="offline-test-answer")
        assert lab.work("assessing")["processedJobs"] == 1
        assert lab.run(receipt["runId"])["status"] == "waiting_for_learner"
        assessed = lab.session(session["id"])
        assert assessed["assessment"]
        assert lab.state(course["id"])["version"] == 1
        assert assessed["activity"]["id"] == session["activity"]["id"]
        lab.next(session["id"])
        assert lab.work("tutoring")["processedJobs"] == 1


def test_failure_trace_omits_exception_content(root, monkeypatch):
    def generate(self, role, instruction, context, schema):
        raise ServiceError(
            "model_request_failed", "Provider body with credential offline-test"
        )

    monkeypatch.setattr(GenerationClient, "generate", generate)
    with Workspace(root) as lab, pytest.raises(ServiceError):
        lab.call(
            "Tutoring",
            "tutoring_chat/chat_prompt",
            {"message": "Help"},
            TutorChatReply,
        )
    trace = json.loads(next((root / "data/traces").glob("*.json")).read_text())
    assert trace["status"] == "failed"
    assert trace["error"] == "model_request_failed"
    assert "offline-test" not in json.dumps(trace)


def test_cli_init_and_missing_course_exit_code(root, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["learnloop_cli", "--workspace", str(root), "init"]
    )
    assert main() == 0
    assert (root / ".gitignore").exists()
    assert json.loads(capsys.readouterr().out)["schema"] == "head"
    monkeypatch.setattr(
        sys,
        "argv",
        ["learnloop_cli", "--workspace", str(root), "courses", "show", "missing"],
    )
    assert main() == 1
    assert "HTTP 404" in capsys.readouterr().err
