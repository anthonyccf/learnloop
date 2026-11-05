import copy
from datetime import UTC, datetime

import pytest

from learnloop.core.schemas import Assessment, PlanChoice
from learnloop.evaluation.artifacts import digest, freeze, read, thaw
from learnloop.evaluation.experiment import run_matrix
from learnloop.evaluation.fixtures import FixtureProvider, prepare_fixture
from learnloop.evaluation.metrics import analyze
from learnloop.evaluation.prepare import (
    load_bundle,
    required_reviews,
    research_gate,
    validate_exams,
)
from learnloop.evaluation.runner import clock_evidence, initialize, run_episode
from learnloop.evaluation.schema import ExperimentConfig, Unit
from learnloop.evaluation.simulator import Student, independent_score
from learnloop.evaluation.variants import matrix


@pytest.fixture
def bundle(tmp_path):
    source = {"chunkId": "p1", "quote": "Subtract the gradient to reduce the loss."}
    unit = Unit.model_validate(
        {
            "id": "test-unit",
            "title": "Workflow-only controlled source fixture",
            "sourceSha256": "a" * 64,
            "passages": [
                {
                    "id": "p1",
                    "text": "Subtract the gradient to reduce the loss. The learning rate controls the update step size.",
                    "document": "fixture.txt",
                    "page": 1,
                }
            ],
            "graph": {
                "concepts": [
                    {
                        "id": f"c{i:02}",
                        "title": f"Concept {i}",
                        "summary": "Use the course source to understand a gradient update.",
                        "sources": [source],
                    }
                    for i in range(10)
                ],
                "prerequisites": [{"prerequisite": "c00", "dependent": "c01", "source": source}],
            },
        }
    )
    path = tmp_path / "bundle"
    prepare_fixture(unit, path)
    return path


def test_full_27_by_four_matrix_resume_and_matched_baselines(bundle, tmp_path):
    config = ExperimentConfig(repeats=1, activities=2, model="workflow-fixture")
    calls = []

    def factory(_):
        provider = FixtureProvider()
        calls.append(provider)
        return provider

    report = run_matrix(bundle, tmp_path / "matrix", config, factory, offline=True)
    assert len(matrix()) == 27 and len({tuple(v.values()) for v in matrix()}) == 27
    assert report["completed"] == 108 and report["failedOrStopped"] == 0
    assert report["balanced27Cells"] and report["gainFactorialEffects"]
    assert report["mode"] == "workflow_only"
    assert report["latencyByRole"]["Simulator"]["calls"] > 0
    resumed = run_matrix(bundle, tmp_path / "matrix", config, factory, offline=True)
    assert len(calls) == 108 and resumed["results"] == report["results"]
    comparison = run_matrix(
        bundle,
        tmp_path / "baselines",
        config,
        factory,
        offline=True,
        selected=matrix()[0],
        baselines=True,
    )
    assert comparison["completed"] == 12
    assert {r["baseline"] for r in comparison["results"]} == {
        "adaptive",
        "fixed_sequence",
        "memory_free",
    }
    with pytest.raises(ValueError, match="manifest changed"):
        run_matrix(
            bundle,
            tmp_path / "matrix",
            config.model_copy(update={"seed": 73}),
            factory,
            offline=True,
        )


def test_hidden_state_and_post_tests_never_reach_tutor_or_assessor(bundle, tmp_path):
    unit, bank, artifacts = load_bundle(bundle)
    bank = copy.deepcopy(bank)
    bank["post"][0]["question"]["prompt"] = "DO_NOT_SEND_POST_TEST_SECRET"

    class Spy(FixtureProvider):
        def generate(self, role, prompt, context, output):
            if role in ("Tutoring", "Assessing"):
                text = str(context)
                assert "DO_NOT_SEND_POST_TEST_SECRET" not in text
                assert all(
                    k not in text
                    for k in (
                        "hiddenAbility",
                        "hiddenProfile",
                        "privateMemory",
                        "canAnswerIndependently",
                    )
                )
            if role == "Simulator" and output.__name__ == "StudentReply":
                assert all(
                    k not in context["question"]
                    for k in ("correctChoiceId", "referenceAnswer", "rubric", "hint", "explanation")
                )
            return super().generate(role, prompt, context, output)

    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "adaptive",
        ExperimentConfig(activities=4),
        Spy(),
        tmp_path / "private",
        mode="workflow_only",
    )
    assert result["status"] == "completed"
    assert not any(
        x["state"] == "demonstrated"
        for levels in initialize(
            [{"id": "pre", "conceptId": "c00", "difficulty": "intermediate", "score": 1}]
        ).values()
        for x in levels.values()
    )
    trace = read(tmp_path / "private" / "trace.json")
    assert "hiddenAbility" not in str(trace) and "DO_NOT_SEND_POST_TEST_SECRET" not in str(trace)


def test_memory_free_resets_only_estimates_and_plans_at_exact_boundary(bundle, tmp_path):
    unit, bank, artifacts = load_bundle(bundle)

    class Spy(FixtureProvider):
        teacher = []

        def generate(self, role, prompt, context, output):
            if role == "Tutoring":
                self.teacher.append(copy.deepcopy(context))
            return super().generate(role, prompt, context, output)

    provider = Spy()
    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "memory_free",
        ExperimentConfig(activities=5),
        provider,
        tmp_path / "memory",
        mode="workflow_only",
    )
    assert result["status"] == "completed"
    trace = read(tmp_path / "memory" / "trace.json")
    boundaries = [row for row in trace if row["boundaryReset"]]
    assert len(boundaries) == 1 and boundaries[0]["index"] == 3
    assert provider.teacher[3]["plan"] == {}
    assert all(
        "lastOutcome" not in r
        for levels in boundaries[0]["evidenceBefore"].values()
        for r in levels.values()
    )
    hidden = read(tmp_path / "memory" / "hidden" / "outcome.json")
    assert hidden["initial"]["memory"] == {} and hidden["final"]["memory"]


def test_clock_and_seed_are_host_independent(bundle):
    unit, _, _ = load_bundle(bundle)
    record = {
        "c00": {"intermediate": {"state": "demonstrated", "reviewAt": "2030-01-08T00:00:00+00:00"}}
    }
    assert (
        clock_evidence(record, datetime(2030, 1, 9, tzinfo=UTC))["c00"]["intermediate"]["state"]
        == "review_due"
    )
    assert (
        clock_evidence(record, datetime(2030, 1, 2, tzinfo=UTC))["c00"]["intermediate"]["state"]
        == "demonstrated"
    )
    students = [Student(unit.graph.model_dump()["concepts"], "novice", 72, 0) for _ in range(2)]
    assert students[0].snapshot() == students[1].snapshot()


def test_budget_and_invalid_action_keep_failed_attempt_without_phantom_metrics(bundle, tmp_path):
    unit, bank, artifacts = load_bundle(bundle)
    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "adaptive",
        ExperimentConfig(activities=2, maxCalls=1),
        FixtureProvider(),
        tmp_path / "budget",
        mode="workflow_only",
    )
    assert result["status"] == "budget_exhausted" and "metrics" not in result
    assert (tmp_path / "budget" / "hidden" / "checkpoint.json").exists()

    class Invalid(FixtureProvider):
        def generate(self, role, prompt, context, output):
            if output is PlanChoice:
                return PlanChoice(
                    candidateId="invented", rationale="An invalid controlled selection."
                )
            return super().generate(role, prompt, context, output)

    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "adaptive",
        ExperimentConfig(activities=2),
        Invalid(),
        tmp_path / "invalid",
        mode="workflow_only",
    )
    assert result["status"] == "failed" and read(tmp_path / "invalid" / "trace.json") == []


def test_unseen_scoring_is_independent_and_teacher_cannot_credit_a_wrong_key(bundle, tmp_path):
    unit, bank, artifacts = load_bundle(bundle)
    from learnloop.evaluation.schema import StudentReply

    reply = StudentReply(
        choiceId="b",
        reasoning="A wrong response",
        hintRequested=False,
        memoryUpdate="",
        learningGain=0,
    )
    assert independent_score(bank["post"][0]["question"], reply)["score"] == 0

    class Lenient(FixtureProvider):
        def generate(self, role, prompt, context, output):
            result = super().generate(role, prompt, context, output)
            if output is Assessment:
                for row in result.coverage:
                    row.score = 1
            return result

    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "adaptive",
        ExperimentConfig(activities=4),
        Lenient(),
        tmp_path / "lenient",
        mode="workflow_only",
    )
    assert result["status"] == "completed"
    assert all(
        row["rubricScore"] == 0
        for row in read(tmp_path / "lenient" / "trace.json")
        if not row["correct"]
    )


def test_artifact_tampering_and_exam_overlap_are_rejected(bundle, tmp_path):
    unit, bank, _ = load_bundle(bundle)
    corrupted = copy.deepcopy(bank)
    corrupted["post"][0]["question"]["prompt"] = corrupted["pre"][0]["question"]["prompt"]
    with pytest.raises(ValueError, match="distinct prompts"):
        validate_exams(unit, corrupted)
    path = tmp_path / "immutable.json"
    freeze(path, {"version": 1})
    with pytest.raises(FileExistsError):
        freeze(path, {"version": 2})
    saved = read(path)
    saved["payload"]["version"] = 2
    path.write_text(__import__("json").dumps(saved))
    with pytest.raises(ValueError, match="hash mismatch"):
        thaw(path)


def test_research_gate_requires_current_screening_and_real_review_records(bundle, monkeypatch):
    unit, bank, artifacts = load_bundle(bundle)
    with pytest.raises(ValueError, match="Workflow fixtures"):
        research_gate(unit, bank, artifacts, {}, {})
    bank["mode"] = "live"
    for artifact in artifacts.values():
        artifact["mode"] = "live"
    requirements = required_reviews(unit, bank, artifacts)
    screening = {
        "unitHash": digest(unit.model_dump()),
        "models": ["judge-one", "judge-two"],
        "items": {
            k: {
                "hash": v,
                "flagged": k.endswith("/c00"),
                "embeddingCosine": 0.9,
                "judgments": [{}, {}],
            }
            for k, v in requirements.items()
            if not k.endswith("/graph") and k.startswith("expert/")
        },
    }
    with pytest.raises(ValueError, match="Human review required"):
        research_gate(unit, bank, artifacts, screening, {})
    reviews = {
        key: {
            "hash": value,
            "decision": "approved",
            "reviewer": "test-only human placeholder",
            "notes": "Controlled test record, not a real approval.",
        }
        for key, value in requirements.items()
    }
    assert "unit" in research_gate(unit, bank, artifacts, screening, reviews)
    from learnloop.evaluation import readiness as preflight

    # Test-only records remain in the temporary fixture directory.
    freeze(bundle / "screening.json", screening)
    freeze(bundle / "reviews.json", reviews)
    monkeypatch.setattr(preflight, "load_bundle", lambda _: (unit, bank, artifacts))
    assert preflight.readiness(bundle)["ready"]
    mismatch = preflight.readiness(bundle, model="different-study-model")
    assert not mismatch["ready"] and mismatch["modelChecked"]
    assert len(mismatch["blockers"]) == 3
    reviews["unit"]["decision"] = "rejected"
    reviews["exams"]["hash"] = "stale"
    del reviews["expert/structural/graph"]
    from learnloop.evaluation.artifacts import checkpoint

    checkpoint(bundle / "reviews.json", {"sha256": digest(reviews), "payload": reviews})
    status = preflight.readiness(bundle)
    assert not status["ready"]
    assert status["reviews"]["unit"] == "rejected"
    assert status["reviews"]["exams"] == "stale"
    assert status["reviews"]["expert/structural/graph"] == "pending"
    reviews["unit"]["hash"] = "stale"
    with pytest.raises(ValueError, match="Human review required"):
        research_gate(unit, bank, artifacts, screening, reviews)


def test_readiness_handles_missing_and_corrupt_artifacts_without_writes(bundle, tmp_path):
    from learnloop.evaluation.readiness import readiness

    absent = tmp_path / "missing-bundle"
    missing = readiness(absent)
    assert not missing["ready"] and len(missing["blockers"]) == 6
    assert not absent.exists()
    freeze(bundle / "screening.json", {})
    assert "Workflow fixtures" in readiness(bundle)["blockers"][0]
    (bundle / "unit.json").write_text("{}", encoding="utf-8")
    assert "Invalid research bundle" in readiness(bundle)["blockers"][0]
    assert not (bundle / "reviews.json").exists()


def test_status_cli_does_not_load_credentials_or_dispatch_providers(tmp_path, monkeypatch, capsys):
    from learnloop.core import config
    from learnloop.evaluation.__main__ import main

    def forbidden():
        raise AssertionError("Readiness must not load service credentials")

    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr("sys.argv", ["evaluation", "status", "--bundle", str(tmp_path / "absent")])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert '"ready": false' in capsys.readouterr().out


def test_no_factorial_effect_claim_for_incomplete_or_unmatched_profiles(bundle, tmp_path):
    report = run_matrix(
        bundle,
        tmp_path / "subset",
        ExperimentConfig(repeats=1, activities=2),
        lambda _: FixtureProvider(),
        offline=True,
        selected=matrix()[0],
    )
    analysis = analyze(report["results"])
    assert not analysis["balanced27Cells"] and analysis["gainFactorialEffects"] == {}


def test_feedback_budget_failure_keeps_a_consistent_checkpoint(bundle, tmp_path):
    from learnloop.evaluation.provider import BudgetExhausted
    from learnloop.evaluation.schema import LearningUpdate

    unit, bank, artifacts = load_bundle(bundle)

    class FailFeedback(FixtureProvider):
        def generate(self, role, prompt, context, output):
            if output is LearningUpdate:
                raise BudgetExhausted("Controlled interruption before the turn commits")
            return super().generate(role, prompt, context, output)

    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "adaptive",
        ExperimentConfig(activities=2),
        FailFeedback(),
        tmp_path / "interrupted",
        mode="workflow_only",
    )
    assert result["status"] == "budget_exhausted"
    state = read(tmp_path / "interrupted" / "hidden" / "checkpoint.json")
    assert state["trace"] == []
    assert all(
        "lastOutcome" not in r for levels in state["evidence"].values() for r in levels.values()
    )


def test_completed_preparation_reuses_source_reviewed_checkpoints(bundle):
    from learnloop.evaluation.prepare import build_expert

    unit, bank, _ = load_bundle(bundle)
    provider = FixtureProvider()
    copy_path = bundle / "same-frozen-content.json"
    build_expert(unit, bank, "structural", provider, copy_path)
    assert provider.calls == []
    assert (
        thaw(copy_path)["payload"]["materials"] == load_bundle(bundle)[2]["structural"]["materials"]
    )


def test_parallel_preparation_preserves_frozen_coverage(bundle, tmp_path):
    from learnloop.evaluation.prepare import build_expert

    unit, bank, _ = load_bundle(bundle)
    result = build_expert(
        unit,
        bank,
        "grounded",
        FixtureProvider(),
        tmp_path / "parallel" / "expert-grounded.json",
        workers=2,
    )
    assert set(result["payload"]["materials"]) == {c.id for c in unit.graph.concepts}


def test_readable_review_packet_is_explicitly_pending_and_contains_private_exam_details(bundle):
    from learnloop.evaluation.review import packet

    path = packet(bundle)
    text = path.read_text(encoding="utf-8")
    assert "PENDING" in text and "No approval is implied" in text
    assert "Post-test" in text and "Key: **a**" in text
    assert not (bundle / "reviews.json").exists()


def test_parallel_checkpoint_writers_reuse_one_complete_reviewed_artifact(bundle, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from learnloop.core.schemas import Graph
    from learnloop.evaluation.prepare import reviewed_generation

    unit, _, _ = load_bundle(bundle)
    context = {
        "concepts": unit.graph.model_dump()["concepts"],
        "passages": [{"chunkId": "p1", "text": unit.passages[0].text}],
    }
    path = tmp_path / "atomic.json"

    def generate(_):
        value, receipt = reviewed_generation(
            unit, FixtureProvider(), "Expert", "Controlled graph.", context, Graph, path
        )
        return value.model_dump(), receipt

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(generate, range(2)))
    assert first == second
    assert thaw(path)["payload"]["content"] == first[0]


def test_screening_caches_model_agreement_and_embedding_checks(bundle, tmp_path):
    from learnloop.evaluation.prepare import screen
    from learnloop.evaluation.schema import Screening

    unit, _, artifacts = load_bundle(bundle)

    class Critic(FixtureProvider):
        def __init__(self, model):
            super().__init__()
            self.model = model

        def generate(self, role, prompt, context, output):
            assert output is Screening
            self.calls.append(
                {"role": role, "inputTokens": 0, "outputTokens": 0, "costUsd": 0, "latencyMs": 0}
            )
            return Screening(
                supported=True,
                appropriateDifficulty=True,
                prerequisiteAccuracy=True,
                notes="Controlled test judgment only.",
            )

    providers = [Critic("test-critic-one"), Critic("test-critic-two")]
    embeddings = []

    def embed(text):
        embeddings.append(text)
        return [1.0, 0.0]

    first = screen(unit, artifacts, providers, embed, "fixture-embedding", tmp_path / "screen")
    assert len(first["items"]) == 30 and len(embeddings) == 60
    assert all(item["modelAgreement"] and not item["flagged"] for item in first["items"].values())
    second = screen(unit, artifacts, providers, embed, "fixture-embedding", tmp_path / "screen")
    assert first["items"] == second["items"] and len(embeddings) == 60


def test_noncompliant_llm_students_cannot_supply_research_score_means(bundle, tmp_path):
    from learnloop.evaluation.schema import StudentReply

    unit, bank, artifacts = load_bundle(bundle)

    class IgnoresProfile(FixtureProvider):
        def generate(self, role, prompt, context, output):
            value = super().generate(role, prompt, context, output)
            if output is StudentReply:
                value.choiceId = "a"
                value.reasoning = "The source supports the selected claim."
            return value

    result = run_episode(
        unit,
        bank,
        artifacts["structural"],
        matrix()[0],
        "novice",
        0,
        "adaptive",
        ExperimentConfig(activities=2),
        IgnoresProfile(),
        tmp_path / "invalid-student",
        mode="research",
    )
    assert result["status"] == "simulation_invalid" and not result["profileControlValid"]
    assert analyze([result])["completed"] == 0


def test_unreviewed_research_stops_before_provider_dispatch(bundle, tmp_path):
    def forbidden(_):
        raise AssertionError("No paid provider may be created before research prerequisites pass")

    with pytest.raises(ValueError, match="recorded human reviews"):
        run_matrix(bundle, tmp_path / "never-started", ExperimentConfig(), forbidden)
    assert not (tmp_path / "never-started").exists()


def test_release_provenance_is_bound_to_unit_and_resume_manifest(bundle, tmp_path):
    from learnloop.evaluation.artifacts import checkpoint

    unit, _, _ = load_bundle(bundle)
    provenance = {
        "releaseId": "release-one",
        "releaseHash": "a" * 64,
        "releaseVersion": 1,
        "courseId": "test-course",
        "unitHash": digest(unit.model_dump()),
    }
    path = bundle / "release-provenance.json"
    freeze(path, provenance)
    config = ExperimentConfig(repeats=1, activities=2)
    output = tmp_path / "release-pinned-run"
    run_matrix(
        bundle, output, config, lambda _: FixtureProvider(), offline=True, selected=matrix()[0]
    )
    assert thaw(output / "manifest.json")["payload"]["courseRelease"] == provenance
    provenance["releaseId"] = "release-two"
    checkpoint(path, {"sha256": digest(provenance), "payload": provenance})
    with pytest.raises(ValueError, match="Resume manifest changed"):
        run_matrix(
            bundle, output, config, lambda _: FixtureProvider(), offline=True, selected=matrix()[0]
        )
    provenance["unitHash"] = "wrong-unit"
    checkpoint(path, {"sha256": digest(provenance), "payload": provenance})
    with pytest.raises(ValueError, match="Release provenance"):
        load_bundle(bundle)
