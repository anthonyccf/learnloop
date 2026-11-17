from types import SimpleNamespace

from learnloop.evaluation.artifacts import thaw
from learnloop.evaluation.fixtures import FixtureProvider
from learnloop.pseudo_experiment import RoutedProvider, make_unit, run
from learnloop.pseudo_retry import inputs, run_retry


class OfflineProvider(FixtureProvider):
    def __init__(self, settings, root, **kwargs):
        super().__init__()


def sample():
    text = (
        "Subtract the gradient to reduce the loss. The learning rate controls the update step size."
    )
    source = {"chunkId": "chunk", "quote": "Subtract the gradient to reduce the loss."}
    release = {
        "documents": [
            {
                "id": "doc",
                "graph": {
                    "concepts": [
                        {
                            "id": "old:concept",
                            "title": "Gradient",
                            "summary": "Use the course source to understand a gradient update.",
                            "sources": [source],
                        }
                    ]
                },
            }
        ],
        "graph": {"prerequisites": []},
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


def test_custom_learner_executes_real_workflow_with_offline_fixtures(tmp_path):
    setup, release = sample()
    unit = make_unit(setup, release, 1)
    assert unit.graph.concepts[0].id == "c01"
    report = run(
        setup,
        release,
        tmp_path / "p",
        {"concepts": 1, "activities": 2, "baselines": True},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=OfflineProvider,
    )
    assert report["mode"] == "exploratory"
    assert report["completed"] == 3
    assert {result["baseline"] for result in report["results"]} == {
        "adaptive",
        "fixed_sequence",
        "memory_free",
    }
    assert all(result["profile"] == "custom" for result in report["results"])


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
                    "id": "other:concept",
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
    setup["material"]["id"] = "__all__"
    with pytest.raises(ValueError, match="one concept per"):
        make_unit(setup, release, 1)
    unit = make_unit(setup, release, 2)
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
        {**config, "sourceRunId": "source-id"},
        SimpleNamespace(llm_model="workflow-fixture"),
        provider_cls=RecordingFixture,
        reused=reused,
    )
    assert report["completed"] == 1
    assert report["preparationUsage"]["calls"] == 0
    assert report["reusedSourceRunId"] == "source-id"
    assert "Tutoring" in calls and "Expert" not in calls and "TestAuthor" not in calls
    assert thaw(output / "exams.json")["payload"] == reused["exams"]


def test_v2_templates_select_base_prompts_for_all_three_agents(tmp_path):
    from learnloop.agents.assessing import prompts_v2 as assessing_v2
    from learnloop.agents.expert import prompts_v2 as expert_v2
    from learnloop.agents.tutoring import prompts_v2 as tutoring_v2
    from learnloop.evaluation.variants import BASE_PROMPTS

    expected = {
        "Expert": expert_v2.EXPERT_MATERIALS_PROMPT,
        "Tutoring": tutoring_v2.PLAN_PROMPT,
        "Assessing": assessing_v2.FEEDBACK_PROMPT,
    }
    for version in ("v1", "v2"):
        prompts = {}

        class RecordingFixture(OfflineProvider):
            def generate(self, role, instruction, context, output):
                if role in expected and output.__name__ != "GroundingReview":
                    prompts.setdefault(role, instruction)
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
        assert set(report["promptVersions"].values()) == {version}
        assert report["completed"] == 1
        assert set(prompts) == set(expected)
        for role, prompt in prompts.items():
            assert prompt.startswith(BASE_PROMPTS[version][role])
            assert (expected[role] in prompt) == (version == "v2")
        variants = report["results"][0]["variants"]
        assert ("promptVersions" in variants) == (version == "v2")


def test_retry_restarts_one_episode_with_frozen_inputs(tmp_path):
    from learnloop.evaluation.artifacts import checkpoint, digest, freeze

    setup, release = sample()
    path = tmp_path / "run"
    settings = SimpleNamespace(llm_model="workflow-fixture")
    config = {"concepts": 1, "activities": 2, "baselines": False}
    run(setup, release, path, config, settings, provider_cls=OfflineProvider)
    freeze(path / "input.json", {"setup": setup, "release": release})
    root = path / "episodes" / digest(["custom", "adaptive"])[:16]
    original = thaw(root / "result.json")
    result = run_retry(
        path,
        "custom",
        "adaptive",
        root / "retries" / "attempt-01",
        settings,
        provider_cls=OfflineProvider,
    )
    assert result["status"] == "completed"
    assert thaw(root / "result.json") == original
    assert result["profile"] == "custom"
    altered = thaw(path / "exams.json")["payload"]
    altered["mode"] = "changed"
    checkpoint(path / "exams.json", {"sha256": digest(altered), "payload": altered})
    import pytest

    with pytest.raises(ValueError, match="Frozen evaluation materials changed"):
        inputs(path, "custom", "adaptive", settings)
