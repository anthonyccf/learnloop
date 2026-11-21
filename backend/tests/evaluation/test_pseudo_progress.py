import json
from datetime import UTC, datetime
from types import SimpleNamespace

from learnloop.evaluation.artifacts import digest, freeze, thaw
from learnloop.evaluation.runner import exam
from learnloop.pseudo_progress import progress


def test_projects_live_and_completed_progress_without_hidden_content(tmp_path):
    setup = {"learners": [{"id": "novice", "name": "Novice"}]}
    job = {"config": {"activities": 5, "baselines": False}}
    root = tmp_path / "episodes" / digest(["novice", "adaptive"])[:16]
    (root / "hidden").mkdir(parents=True)
    trace = [
        {
            "index": 0,
            "selected": {"conceptId": "c01", "title": "Concept", "secret": "private-question"},
            "difficulty": "basic",
            "before": "developing",
            "after": "developing",
            "correct": False,
            "hinted": True,
            "session": 0,
        },
        {
            "index": 1,
            "selected": {"conceptId": "c01", "title": "Concept"},
            "difficulty": "basic",
            "before": "developing",
            "after": "demonstrated",
            "correct": True,
            "hinted": False,
            "session": 0,
        },
        {
            "index": 2,
            "selected": {"conceptId": "c01", "title": "Concept"},
            "difficulty": "basic",
            "before": "demonstrated",
            "after": "demonstrated",
            "correct": True,
            "hinted": False,
            "session": 1,
        },
    ]
    (root / "hidden" / "checkpoint.json").write_text(
        json.dumps({"trace": trace, "student": {"knowledge": "hidden-secret"}}), encoding="utf-8"
    )
    live = progress(tmp_path, setup, job, "running")[0]
    assert live["status"] == "in_progress"
    assert (live["activitiesCompleted"], live["correctAnswers"], live["hintsUsed"]) == (3, 2, 1)
    assert live["milestones"] == [
        {"concept": "Concept", "difficulty": "basic", "activity": 2, "levelActivities": 2}
    ]
    assert "hidden-secret" not in json.dumps(live) and "private-question" not in json.dumps(live)
    (root / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    freeze(
        root / "result.json",
        {
            "status": "completed",
            "metrics": {
                "preScore": 0.1,
                "postScore": 0.9,
                "activitiesAtVerifiedTarget": 3,
                "postTestMasteredConcepts": 1,
            },
        },
    )
    final = progress(tmp_path, setup, job, "completed")[0]
    assert final["status"] == "completed" and final["verifiedTargetActivities"] == 3
    assert final["postScore"] == 0.9
    assert final["examProgress"] is None
    (root / "exam-progress.json").write_text(
        json.dumps({"phase": "pre", "completed": 4, "total": 15, "prompt": "hidden exam"}),
        encoding="utf-8",
    )
    running = progress(tmp_path, setup, job, "running")[0]
    assert running["examProgress"] is None
    (root / "result.json").unlink()
    (root / "trace.json").unlink()
    during_exam = progress(tmp_path, setup, job, "running")[0]
    assert during_exam["examProgress"] == {"phase": "pre", "completed": 4, "total": 15}
    assert "hidden exam" not in json.dumps(during_exam)


def test_retry_progress_preserves_original_attempt_history(tmp_path):
    setup = {"learners": [{"id": "novice", "name": "Novice"}]}
    job = {"config": {"activities": 3, "baselines": False}}
    root = tmp_path / "episodes" / digest(["novice", "adaptive"])[:16]
    freeze(root / "result.json", {"status": "failed", "errorType": "ValueError"})
    (root / "trace.json").write_text("[]", encoding="utf-8")
    initial = progress(tmp_path, setup, job, "completed_with_failures")[0]
    assert initial["canRetry"] and initial["attempt"] == 1
    retry = root / "retries" / "attempt-01"
    retry.mkdir(parents=True)
    (retry / "retry-status.json").write_text('{"status":"running"}', encoding="utf-8")
    live = progress(tmp_path, setup, job, "completed_with_failures")[0]
    assert live["status"] == "in_progress" and live["attempt"] == 2
    assert not live["canRetry"] and live["previousAttempts"][0]["errorType"] == "ValueError"
    freeze(retry / "result.json", {"status": "completed", "metrics": {"postScore": 0.8}})
    final = progress(tmp_path, setup, job, "completed_with_failures")[0]
    assert final["status"] == "completed" and not final["canRetry"]
    assert thaw(root / "result.json")["payload"]["status"] == "failed"


def test_never_started_or_interrupted_episodes_are_not_called_complete(tmp_path):
    setup = {"learners": [{"id": "learner", "name": "A"}]}
    job = {"config": {"activities": 2, "baselines": True}}
    running = progress(tmp_path, setup, job, "running")
    assert len(running) == 3 and all(item["status"] == "not_started" for item in running)
    root = tmp_path / "episodes" / digest(["learner", "adaptive"])[:16]
    root.mkdir(parents=True)
    assert progress(tmp_path, setup, job, "failed")[0]["status"] == "interrupted"


def test_exam_reports_question_counts_without_leaking_prompts():
    class Stub:
        def respond(self, provider, concept, question, phase, at):
            return SimpleNamespace(choiceId="a"), None

        def record_score(self, correct):
            self.correct = correct

    question = {
        "difficulty": "basic",
        "correctChoiceId": "a",
        "prompt": "hidden exam prompt",
        "rubric": [{"weight": 1, "choiceScores": {"a": 1}}],
    }
    seen = []
    results = exam(
        {"pre": [{"id": "q1", "conceptId": "c", "question": question}]},
        "pre",
        Stub(),
        None,
        datetime.now(UTC),
        on_progress=lambda completed, total: seen.append((completed, total)),
    )
    assert seen == [(0, 1), (1, 1)]
    assert results[0]["correct"] is True
    assert "hidden exam prompt" not in json.dumps(seen)
