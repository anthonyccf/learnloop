import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from learnloop.core.grounding import remap_sources
from learnloop.core.schemas import DifficultyMaterials, Question, QuestionKeyCheck
from learnloop.evaluation.artifacts import thaw
from learnloop.evaluation.fixtures import FixtureProvider, question
from learnloop.pseudo_experiment import RoutedProvider, published_unit, run
from learnloop.pseudo_retry import inputs, run_retry


class OfflineProvider(FixtureProvider):
    def __init__(self, settings, root, **kwargs):
        super().__init__()

    def generate(self, role, instruction, context, output):
        if output is Question:
            return Question.model_validate(
                question(
                    context["concept"],
                    context["passages"][0],
                    context["difficulty"],
                    f"practice-{len(context['previousPrompts'])}",
                )
            )
        if output is QuestionKeyCheck:
            return QuestionKeyCheck(answers=["a"] * len(context["questions"]))
        return super().generate(role, instruction, context, output)


def sample():
    text = (
        "Subtract the gradient to reduce the loss. The learning rate controls the update step size."
    )
    source = {"chunkId": "chunk", "quote": "Subtract the gradient to reduce the loss."}
    concept = {
        "id": "gradient",
        "title": "Gradient",
        "summary": "Use the course source to understand a gradient update.",
        "sources": [source],
    }
    fixture_pack = FixtureProvider().generate(
        "Expert",
        "",
        {"concept": concept, "passages": [{**source, "text": text}]},
        DifficultyMaterials,
    )
    published_pack = {
        "lesson": fixture_pack.lesson.as_lesson(),
        "tests": [q.model_dump() for q in fixture_pack.tests if q.difficulty == "basic"],
    }
    release = {
        "documents": [
            {
                "id": "doc",
                "graph": {
                    "concepts": [concept],
                    "resources": {concept["id"]: published_pack},
                },
            }
        ],
        "graph": {"concepts": [concept], "prerequisites": []},
        "chunks": {"chunk": {"text": text, "page": 1, "label": "notes.txt"}},
    }
    learner = {
        "id": "custom",
        "name": "Custom",
        "model": "model-a",
        "basic": 0.5,
        "intermediate": 0.4,
        "advanced": 0.3,
        "hint": 0.2,
        "gain": 0.05,
        "delaySeconds": 20,
        "misconceptions": False,
    }
    setup = {
        "material": {"id": "doc", "filename": "notes.txt", "sha256": "a" * 64},
        "templates": {"expert": None, "tutor": None, "assessing": None},
        "learners": [learner],
    }
    return setup, release


def test_course_payload_keeps_lessons_when_release_ids_differ():
    from learnloop.agents.expert.materials import material_valid
    from learnloop.pseudo_workbench import course_payload

    setup, release = sample()
    unit, materials = published_unit(setup, release, 1)
    payload = course_payload(
        {"documents": [], "graph": {"concepts": [], "prerequisites": []}, "chunks": {}},
        unit,
        "course",
        materials,
    )
    concept_id = unit.graph.concepts[0].id
    saved = payload["documents"][0]["graph"]["resources"][concept_id]
    chunks = {chunk_id: {"text": chunk["text"]} for chunk_id, chunk in payload["chunks"].items()}
    assert material_valid(saved, chunks)
    assert set(payload["chunks"]) == {passage.id for passage in unit.passages}


def test_storage_name_drops_windows_reserved_characters():
    from learnloop.evaluation.artifacts import storage_name

    name = storage_name("6b79e617-9e77-44fb-ba3e-2e8d9daa6d97:mha-score-matrix-memory")
    assert ":" not in name
    assert storage_name("gradient") == "gradient"


def test_published_unit_keeps_workbench_concept_ids():
    setup, release = sample()
    concept_id = "6b79e617-9e77-44fb-ba3e-2e8d9daa6d97:mha-score-matrix-memory"
    release["graph"]["concepts"][0]["id"] = concept_id
    release["documents"][0]["graph"]["concepts"][0]["id"] = concept_id
    pack = release["documents"][0]["graph"]["resources"].pop("gradient")
    release["documents"][0]["graph"]["resources"][concept_id] = pack
    unit, materials = published_unit(setup, release, 1)
    assert unit.graph.concepts[0].id == concept_id
    assert concept_id in materials


def test_custom_learner_executes_real_workflow_with_offline_fixtures(tmp_path):
    setup, release = sample()
    unit, published = published_unit(setup, release, 1)
    assert unit.graph.concepts[0].id == "gradient"
    report = run(
        setup,
        release,
        tmp_path / "p",
        {"concepts": 1, "activities": 2, "baselines": True},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=OfflineProvider,
    )
    assert report["mode"] == "exploratory"
    assert report["completed"] == 1
    assert [result["baseline"] for result in report["results"]] == ["adaptive"]
    assert report["results"][0]["metrics"]["activities"] == 2
    assert all(result["profile"] == "custom" for result in report["results"])
    original = published["gradient"]["content"]
    saved = thaw(tmp_path / "p" / "expert.json")["payload"]
    pack = saved["materials"]["gradient"]["content"]
    assert saved["materialSource"] == "workbench_generated"
    assert pack["basicLesson"] == pack["advancedLesson"] == original["lesson"]
    assert pack["tests"] == original["tests"]
    assert [q["difficulty"] for q in pack["tests"]] == ["basic", "basic"]


def test_exploratory_episode_uses_workbench_agent_prompts(tmp_path):
    from learnloop.agents.tutoring.prompts import PLAN_PROMPT

    class RecordingProvider(OfflineProvider):
        requests = []

        def generate(self, role, prompt, context, output):
            self.requests.append((role, prompt, context, output.__name__))
            return super().generate(role, prompt, context, output)

    setup, release = sample()
    report = run(
        setup,
        release,
        tmp_path / "run",
        {"concepts": 1, "activities": 2, "baselines": False},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=RecordingProvider,
    )
    assert report["completed"] == 1
    decisions = [r for r in RecordingProvider.requests if r[3] == "WorkbenchDecision"]
    plans = [r for r in RecordingProvider.requests if r[3] == "PlanChoice"]
    assert decisions and plans
    assert all(r[1] == PLAN_PROMPT and "learnerMemory" in r[2] for r in plans)
    assert any(r[3] == "GroundingReview" for r in RecordingProvider.requests)


def test_workbench_generation_reuses_saved_practice_materials(tmp_path):
    setup, release = sample()
    setup.update(materialSource="workbench_generated", workbenchRunId="source-run")
    _, original = published_unit(setup, release, 1)
    report = run(
        setup,
        release,
        tmp_path / "run",
        {"concepts": 1, "activities": 2, "baselines": False},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=OfflineProvider,
    )
    artifact = thaw(tmp_path / "run" / "expert.json")["payload"]
    assert artifact["materials"] == original
    assert report["completed"] == 1
    assert report["results"][0]["metrics"]["activities"] == 2
    assert (tmp_path / "run" / "exams.json").exists()


def test_all_materials_sample_each_document_and_bound_scope():
    import pytest

    setup, release = sample()
    source = release["chunks"]["chunk"]
    source["document_id"] = "doc"
    second = {
        "id": "doc2",
        "graph": {
            "concepts": [
                {
                    "id": "other-concept",
                    "title": "Other concept",
                    "summary": "Understand the course source and its gradient update.",
                    "sources": [
                        {"chunkId": "chunk2", "quote": "Subtract the gradient to reduce the loss."}
                    ],
                }
            ]
        },
    }
    release["documents"].append(second)
    release["chunks"]["chunk2"] = {**source, "document_id": "doc2", "label": "other.txt"}
    release["graph"]["concepts"].extend(second["graph"]["concepts"])
    original = release["documents"][0]["graph"]["resources"]["gradient"]
    second["graph"]["resources"] = {"other-concept": remap_sources(original, {"chunk": "chunk2"})}
    setup["material"]["id"] = "__all__"
    with pytest.raises(ValueError, match="larger concept limit"):
        published_unit(setup, release, 1)
    unit, _ = published_unit(setup, release, 2)
    assert [concept.title for concept in unit.graph.concepts] == ["Gradient", "Other concept"]
    assert {p.document for p in unit.passages} == {"notes.txt", "other.txt"}


def test_routing_applies_saved_template_and_learner_model_only_to_matching_roles():
    class Recording:
        model, temperature = "default", 0.2

        def generate(self, role, prompt, context, output):
            return self.model, self.temperature, prompt

    class PlanChoice:
        pass

    class StudentReply:
        pass

    class ExamDraft:
        pass

    base = Recording()
    provider = RoutedProvider(
        base,
        {
            "tutor": {
                "model": "tutor-model",
                "temperature": 0.7,
                "prompts": {"analysis": "custom instruction"},
            }
        },
        {"model": "student-model"},
    )
    model, temperature, prompt = provider.generate("Tutoring", "base", {}, PlanChoice)
    assert (model, temperature) == ("tutor-model", 0.7) and "custom instruction" in prompt
    assert provider.generate("Simulator", "student", {}, StudentReply)[0] == "student-model"
    assert provider.generate("TestAuthor", "exam", {}, ExamDraft) == ("default", 0.2, "exam")
    assert (base.model, base.temperature) == ("default", 0.2)


def test_reused_tutor_run_makes_no_expert_or_exam_generation_calls(tmp_path):
    setup, release = sample()
    first = tmp_path / "first"
    config = {"concepts": 1, "activities": 2, "baselines": False}
    run(
        setup,
        release,
        first,
        config,
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=OfflineProvider,
    )
    reused = {
        key: thaw(first / filename)["payload"]
        for key, filename in (
            ("unit", "unit.json"),
            ("exams", "exams.json"),
            ("expert", "expert.json"),
        )
    }
    calls = []

    class RecordingFixture(OfflineProvider):
        def generate(self, role, instruction, context, output):
            calls.append(role)
            return super().generate(role, instruction, context, output)

    output = tmp_path / "second"
    report = run(
        setup,
        release,
        output,
        {**config, "sourceRunId": "source-id", "simulator": "belief"},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=RecordingFixture,
        reused=reused,
    )
    assert report["completed"] == 1
    assert report["preparationUsage"]["calls"] == 0
    assert report["reusedSourceRunId"] == "source-id"
    assert report["results"][0]["metrics"]["simulationPolicyAgreement"] is None
    assert "Tutoring" in calls and "TestAuthor" not in calls
    assert thaw(output / "exams.json")["payload"] == reused["exams"]


def test_v2_templates_use_workbench_questions_and_evaluation_tutor_and_assessing(tmp_path):
    from learnloop.agents.expert import prompts as expert_prompts
    from learnloop.agents.tutoring import prompts as tutoring_prompts

    for version in ("v1", "v2"):
        prompts = {}

        class RecordingFixture(OfflineProvider):
            def generate(self, role, instruction, context, output):
                prompts.setdefault(output.__name__, instruction)
                return super().generate(role, instruction, context, output)

        setup, release = sample()
        if version == "v2":
            setup["templates"] = {
                agent: {"agent": agent, "prompts": {}, "basePrompts": "v2"}
                for agent in ("expert", "tutor", "assessing")
            }
        report = run(
            setup,
            release,
            tmp_path / version,
            {"concepts": 1, "activities": 2, "baselines": False},
            SimpleNamespace(llm_model="workflow-fixture"),
            provider_cls=RecordingFixture,
        )
        assert set(report["promptVersions"].values()) == {"v2"}
        assert report["completed"] == 1
        assert prompts["PlanChoice"] == tutoring_prompts.PLAN_PROMPT
        assert expert_prompts.MIXED_PROMPT in prompts["MultipleAnswerQuestion"]
        variants = report["results"][0]["variants"]
        assert variants["promptVersions"] == {"expert": "v2", "tutor": "v2", "assessor": "v2"}


def test_retry_restarts_one_episode_with_frozen_inputs(tmp_path):
    from learnloop.evaluation.artifacts import checkpoint, digest, freeze

    setup, release = sample()
    path = tmp_path / "run"
    settings = SimpleNamespace(llm_model="workflow-fixture")
    config = {"concepts": 1, "activities": 2, "baselines": False, "simulator": "belief"}
    run(setup, release, path, config, settings, provider_cls=OfflineProvider)
    freeze(path / "input.json", {"setup": setup, "release": release})
    root = path / "episodes" / digest(["custom", "adaptive"])[:16]
    original = thaw(root / "result.json")
    checkpoint(path / "status.json", {"status": "completed_with_failures"})
    result = run_retry(
        path,
        "custom",
        "adaptive",
        root / "retries" / "attempt-01",
        settings,
        provider_cls=OfflineProvider,
    )
    assert result["status"] == "completed"
    assert json.loads((path / "status.json").read_text()) == {"status": "completed_with_failures"}
    assert thaw(root / "result.json") == original
    assert result["profile"] == "custom"
    assert result["metrics"]["simulationPolicyAgreement"] is None
    altered = thaw(path / "exams.json")["payload"]
    altered["mode"] = "changed"
    checkpoint(path / "exams.json", {"sha256": digest(altered), "payload": altered})
    import pytest

    with pytest.raises(ValueError, match="Frozen evaluation materials changed"):
        inputs(path, "custom", "adaptive", settings)


def test_pseudo_job_imports_in_a_fresh_process():
    backend = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", "import learnloop.pseudo_experiment_job"],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_delivered_lesson_reaches_student_and_mixed_answers_match_format(tmp_path):
    from datetime import UTC, datetime

    from learnloop.evaluation.belief_student import BeliefStudent
    from learnloop.evaluation.schema import MixedStudentReply, StudentBlankAnswer
    from learnloop.pseudo_experiment import episode_limits
    from learnloop.pseudo_workbench import answer_body

    teaching_seen = []
    formats_seen = []

    class RecordingFixture(OfflineProvider):
        def generate(self, role, instruction, context, output):
            if role == "Simulator" and output.__name__ in ("StudentReply", "MixedStudentReply"):
                if context.get("phase") == "train":
                    teaching_seen.append(context.get("teaching"))
                    formats_seen.append(context["question"].get("format", "single_answer"))
            return super().generate(role, instruction, context, output)

    setup, release = sample()
    report = run(
        setup,
        release,
        tmp_path / "run",
        {"concepts": 1, "activities": 2, "baselines": False},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=RecordingFixture,
    )
    assert report["completed"] == 1
    assert teaching_seen and all(isinstance(lesson, dict) for lesson in teaching_seen)
    assert "multiple_answer" in formats_seen

    multi = answer_body(
        {"format": "multiple_answer", "choices": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
        MixedStudentReply(
            choiceIds=["a", "c"],
            reasoning="Both apply.",
            hintRequested=False,
            memoryUpdate="",
            learningGain=0,
        ),
    )
    assert multi == {"choiceIds": ["a", "c"]}

    fill = answer_body(
        {"format": "fill_in", "blankIds": ["term", "metric"]},
        MixedStudentReply(
            blanks=[
                StudentBlankAnswer(id="term", text="gradient"),
                StudentBlankAnswer(id="metric", text="loss"),
            ],
            reasoning="Long explanation that must not go into the blanks.",
            hintRequested=False,
            memoryUpdate="",
            learningGain=0,
        ),
    )
    assert fill == {
        "blanks": [{"id": "term", "text": "gradient"}, {"id": "metric", "text": "loss"}]
    }

    # BeliefStudent guesses safely on fill_in and open questions with empty choices.
    belief = BeliefStudent(
        [{"id": "c1", "title": "C1", "summary": "S1"}],
        "novice",
        72,
        0,
        {
            "ability": [0.0, 0.0, 0.0],
            "hint": 0.0,
            "gain": 0.05,
            "delay": 1000,
            "misconceptions": False,
        },
    )
    belief.beliefs = {"c1": {}}
    at = datetime.now(UTC)
    fill_reply, _ = belief.respond(
        OfflineProvider(None, None),
        "c1",
        {
            "difficulty": "basic",
            "prompt": "Fill [term]",
            "choices": [],
            "format": "fill_in",
            "blankIds": ["term"],
        },
        "train",
        at,
    )
    assert answer_body({"format": "fill_in", "blankIds": ["term"]}, fill_reply) == {
        "blanks": [{"id": "term", "text": "unsure"}]
    }
    open_reply, _ = belief.respond(
        OfflineProvider(None, None),
        "c1",
        {"difficulty": "basic", "prompt": "Explain why.", "choices": [], "format": "open"},
        "train",
        at,
    )
    assert answer_body({"format": "open"}, open_reply) == {"answerText": "I am not sure."}

    calls_10, tokens_10 = episode_limits(10, 4)
    assert calls_10 > 60 + 48 and tokens_10 >= calls_10 * 5000


def test_workbench_services_match_live_llm_settings_and_query_retrieval(monkeypatch, tmp_path):
    import httpx
    from pydantic import SecretStr

    from learnloop.core.schemas import GroundingReview
    from learnloop.evaluation.provider import Provider
    from learnloop.pseudo_workbench import WorkbenchServices

    sent = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            sent.append(json)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "model": json["model"],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "cost": 0.0001},
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"status":"supported","summary":"Supported by source."}'
                            },
                        }
                    ],
                },
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)
    settings = SimpleNamespace(
        llm_model="main-model",
        expert_verifier_model="verifier-model",
        llm_api_key=SecretStr("secret"),
        llm_base_url="https://example.invalid",
        request_timeout_seconds=90,
    )
    chunks = {
        f"c{i}": {"id": f"c{i}", "document_id": "d1", "text": f"Unrelated slide {i}."}
        for i in range(6)
    }
    chunks["c6"] = {
        "id": "c6",
        "document_id": "d1",
        "text": "Paged attention allocates fixed-size KV blocks dynamically.",
    }
    concepts = [
        {
            "id": "paged-kv",
            "title": "Paged KV block allocation",
            "summary": "Fixed-size KV blocks for attention cache",
            "sources": [{"chunkId": "c6", "quote": "fixed-size KV blocks"}],
        }
    ]
    services = WorkbenchServices(settings, chunks, concepts=concepts)
    provider = Provider(settings, tmp_path, max_calls=10, max_tokens=100000)
    services.bind(provider, {"model": "configured"})

    hits = services.search(
        "Paged KV block allocation Fixed-size KV blocks for attention cache",
        "local-owner",
        "course-1",
        ["d1"],
        limit=2,
    )
    assert hits[0] == "c6"

    services.generate("Tutoring", "Choose next step.", {"x": 1}, GroundingReview)
    services.verify("Check support.", {"x": 1}, GroundingReview)
    assert len(sent) == 2
    assert sent[0]["messages"][0]["content"].startswith("You are the LearnLoop Tutoring Agent.")
    assert "temperature" not in sent[0]
    assert "seed" not in sent[0]
    assert sent[0]["max_tokens"] == 2500
    assert sent[1]["model"] == "verifier-model"
    assert sent[1]["max_tokens"] == 6000
    assert services.last_resolved_model == "verifier-model"
    assert services.last_generation_usage["inputTokens"] == 20

    # Schema validation failures translate to ServiceError("invalid_model_output") like Services.
    import pytest

    from learnloop.core.errors import ServiceError

    class BadOutputProvider:
        model = "main-model"
        temperature = 0.2
        calls = []

        def generate(self, role, instruction, context, output):
            output.model_validate_json('{"bad": true}')

    services.bind(BadOutputProvider(), {"model": "configured"})
    with pytest.raises(ServiceError) as exc_info:
        services.generate("Expert", "Write a question.", {}, GroundingReview)
    assert exc_info.value.code == "invalid_model_output"

def test_step_uses_parent_outcome_when_expert_handoff_fails():
    import pytest

    from learnloop.pseudo_workbench import check_step

    view = {"handoffs": [{"status": "failed"}], "runs": [{"status": "waiting_for_learner"}]}
    check_step(view)
    view["runs"][-1] = {"status": "needs_review", "summary": "Source review failed"}
    with pytest.raises(RuntimeError, match="Source review failed"):
        check_step(view)
