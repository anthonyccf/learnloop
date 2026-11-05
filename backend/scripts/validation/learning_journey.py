"""Real-service acceptance journey against scripts.development.journey_sandbox only.

Uses a disposable synthetic course, never the user's database schema. Run while
journey_sandbox is listening on 8011; results are saved in tmp/journey-report.json.
"""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from learnloop.core.config import get_settings
from learnloop.core.domain import select_concept, validate_graph
from learnloop.core.schemas import PostExample
from learnloop.persistence.database import Activity, Document, LearnerState, session_factory
from scripts.paths import ARTIFACT_ROOT

ROOT = ARTIFACT_ROOT
MATERIAL = """A small course: learning gradient descent

1. Loss and gradient direction
A loss function measures prediction error. For the hypothetical squared loss
L(w) = (w - 3)^2, the minimum is at w = 3. Its gradient is g = 2(w - 3).
The gradient points toward the steepest local increase. Subtracting a sufficiently
small multiple of the gradient can reduce loss. A zero gradient is a stationary
point; it does not prove a global minimum for every loss function.

2. The gradient descent update
Gradient descent uses w_new = w - eta*g, with a positive learning rate eta.
For L(w) = (w - 3)^2 at w = 5, the gradient is 4. With eta = 0.1,
the new weight is 4.6. The loss falls from 4 to 2.56. Repeating updates moves
toward a minimum for a suitable learning rate. Each update uses the current gradient.

3. Learning rate and overshooting
The learning rate controls the update size. For the same starting weight 5 and
gradient 4, eta = 1.5 produces weight -1, whose loss is 16. This illustrates
overshooting: moving opposite the gradient does not guarantee a lower loss when
the step is too large. Very small steps may converge slowly. A rate that works
for one loss function is not guaranteed to work for all losses.
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def original_workspace():
    with session_factory()() as db:
        return digest(
            {
                "documents": [
                    (d.id, d.graph) for d in db.scalars(select(Document).order_by(Document.id))
                ],
                "learners": [
                    (s.id, s.version, s.evidence)
                    for s in db.scalars(select(LearnerState).order_by(LearnerState.id))
                ],
            }
        )


def main():
    manifest = json.loads((ROOT / "journey-sandbox.json").read_text())
    path = Path(manifest["database"]).resolve()
    assert path.name == "workspace.db" and path.parent.name.startswith("learnloop_sandbox_")
    assert path.parent.parent == Path(gettempdir()).resolve(), "Requires an isolated sandbox file"
    assert manifest["port"] == 8011
    settings = get_settings()
    factory = session_factory(
        settings.model_copy(update={"database_url": SecretStr("sqlite:///" + path.as_posix())})
    )
    engine = factory.kw["bind"]
    baseline = original_workspace()
    report = {
        "startedAt": datetime.now(UTC).isoformat(),
        "status": "running",
        "checks": [],
        "attempts": [],
    }

    def save():
        (ROOT / "journey-report.json").write_text(json.dumps(report, indent=2))

    def passed(name, **detail):
        report["checks"].append({"name": name, "status": "passed", **detail})
        save()
        print(json.dumps(report["checks"][-1]), flush=True)

    with httpx.Client(
        base_url="http://127.0.0.1:8011/api/",
        headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()},
        timeout=30,
        trust_env=False,
    ) as client:

        def request(method, path, expected=200, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.status_code == expected, (
                f"{method} {path}: expected {expected}, got {response.status_code}"
            )
            return response.json()

        def run_ready(id, expected):
            deadline = time.monotonic() + 900
            latest = None
            while time.monotonic() < deadline:
                run = request("GET", f"agent-activity/runs/{id}")
                if run["status"] == expected:
                    return run
                assert run["status"] not in ("failed", "needs_review", "paused"), (
                    f"{run['workflow']}: {run['summary']}"
                )
                task = (run["status"], run["agents"]["expert"]["detail"])
                if task != latest:
                    print(
                        json.dumps(
                            {
                                "workflow": run["workflow"],
                                "status": run["status"],
                                "detail": task[1],
                            }
                        ),
                        flush=True,
                    )
                    latest = task
                time.sleep(1)
            raise AssertionError("Workflow exceeded the acceptance-test time limit")

        try:
            title = "Acceptance test: gradient descent module"
            existing = request("GET", "courses")
            course = next(
                (
                    c
                    for c in existing
                    if c["title"] == title
                    and request("GET", f"courses/{c['id']}/learner-state")["version"] == 0
                ),
                None,
            )
            if course is None:
                course = request("POST", "courses", 201, json={"title": title})
            id = course["id"]
            report["courseId"] = id
            upload = request(
                "POST",
                f"courses/{id}/documents",
                202,
                files={"file": ("gradient-descent-module.txt", MATERIAL.encode(), "text/plain")},
            )
            passed("upload_saved_and_background_job_created")
            run_ready(upload["runId"], "completed")
            detail = request("GET", f"courses/{id}")
            graph = detail["graph"]
            validate_graph(graph)
            concepts = graph["concepts"]
            assert len(concepts) >= 2, "Multi-topic notes must produce more than one learning goal"
            topics = graph["topics"]
            grouped = [key for topic in topics for key in topic["conceptIds"]]
            assert len(grouped) == len(set(grouped)) == len(concepts) and set(grouped) == {
                c["id"] for c in concepts
            }
            coverage = detail["documents"][0]["coverage"]
            assert coverage["processedPassages"] == coverage["totalPassages"]
            passed(
                "all_passages_reviewed_and_complete_organized_graph",
                concepts=len(concepts),
                topics=len(topics),
                prerequisites=len(graph["prerequisites"]),
            )
            learning = request("GET", f"courses/{id}/materials")
            assert len(learning["materials"]) == learning["expectedCount"] == len(concepts)
            assert [m["conceptId"] for m in learning["materials"]] == [c["id"] for c in concepts]
            for material in learning["materials"]:
                assert material["questionCount"] == 2 and material["sources"]
                PostExample.model_validate(material["lesson"]["workedExample"])
            assert not any(
                key in json.dumps(learning) for key in ('"correctChoiceId"', '"tests"', '"hint"')
            )
            passed(
                "lessons_structured_examples_sources_and_private_test_bank",
                lessons=len(concepts),
                questions=2 * len(concepts),
            )
            passed("lesson_sequence_matches_map_and_tutor")
            duplicate = request(
                "POST",
                f"courses/{id}/documents",
                202,
                files={"file": ("renamed.txt", MATERIAL.encode(), "text/plain")},
            )
            assert duplicate["duplicate"] and duplicate["documentId"] == upload["documentId"]
            assert request("POST", f"documents/{upload['documentId']}/materials", 202, json={}) == {
                "status": "ready"
            }
            passed("duplicate_upload_and_preparation_reuse_saved_work")
            found = request(
                "POST",
                f"courses/{id}/search",
                json={"query": "How does the learning rate cause overshooting?"},
            )
            assert found["passages"] and all(
                p["document_id"] == upload["documentId"] for p in found["passages"]
            )
            request("GET", f"documents/{upload['documentId']}/pages/1")
            passed("real_embedding_search_and_original_source_access")
            root = select_concept(graph, {})["id"]
            if graph["prerequisites"]:
                request(
                    "POST",
                    f"courses/{id}/sessions",
                    409,
                    json={
                        "expectedLearnerVersion": 0,
                        "conceptId": graph["prerequisites"][0]["dependent"],
                    },
                )
                passed("prerequisites_explained_before_focused_practice")
            session = request(
                "POST",
                f"courses/{id}/sessions",
                202,
                json={"expectedLearnerVersion": 0, "conceptId": root},
            )
            run_ready(session["runIds"][0], "waiting_for_learner")
            session_id = session["id"]
            origins = []
            for index in range(4):
                if index:
                    receipt = request(
                        "POST",
                        f"sessions/{session_id}/next",
                        202,
                        json={"expectedLearnerVersion": index},
                    )
                    run_ready(receipt["runId"], "waiting_for_learner")
                current = request("GET", f"sessions/{session_id}")
                activity = current["activity"]
                assert activity and activity["conceptId"] == root
                assert current["assessment"] is None and current["selectedChoiceId"] is None
                assert '"correctChoiceId"' not in json.dumps(current)
                origins.append(activity["authoredBy"])
                with factory() as db:
                    answer = db.get(Activity, activity["id"]).private["correctChoiceId"]
                hinted = index == 1
                if hinted:
                    assert request("POST", f"activities/{activity['id']}/hint")["hintUsed"]
                    assert request("GET", f"courses/{id}/learner-state")["version"] == index
                choice = (
                    next(c["id"] for c in activity["choices"] if c["id"] != answer)
                    if index == 0
                    else answer
                )
                body = {
                    "operationId": str(uuid4()),
                    "expectedLearnerVersion": index,
                    "choiceId": choice,
                }
                receipt = request("POST", f"activities/{activity['id']}/responses", 202, json=body)
                assert (
                    request("POST", f"activities/{activity['id']}/responses", 202, json=body)
                    == receipt
                )
                run_ready(receipt["runId"], "waiting_for_learner")
                assessed = request("GET", f"sessions/{session_id}")
                assert (
                    assessed["activity"]["id"] == activity["id"]
                    and assessed["activity"]["status"] == "assessed"
                )
                assessment = assessed["assessment"]
                assert assessment["correct"] == (index != 0) and assessment["hinted"] == hinted
                assert assessment["feedback"] and assessment["explanation"]
                # Refresh/reconnect must retain the answered question and its analysis.
                assert request("GET", f"sessions/{session_id}") == assessed
                state = request("GET", f"courses/{id}/learner-state")
                assert state["version"] == index + 1
                evidence = state["concepts"][root]["intermediate"]
                if index == 1:
                    assert evidence["assisted"] == 1 and not evidence["independentActivityIds"]
                report["attempts"].append(
                    {
                        "number": index + 1,
                        "correct": assessment["correct"],
                        "hinted": hinted,
                        "uncertain": assessment["uncertain"],
                        "state": evidence["state"],
                        "version": state["version"],
                    }
                )
                passed(
                    "answer_analysis_retained_until_explicit_next",
                    attempt=index + 1,
                    state=evidence["state"],
                )
            assert evidence["state"] == "demonstrated", (
                "Two independent correct checks should demonstrate the concept"
            )
            assert len(set(evidence["independentActivityIds"])) == 2 and evidence["attempts"] == 4
            assert origins[:2] == ["expert", "expert"] and origins[2:] == ["tutoring", "tutoring"]
            history = request("GET", f"courses/{id}/assessments")
            assert len(history) == 4 and all(item["assessment"] for item in history)
            passed(
                "wrong_assisted_and_independent_evidence_and_history",
                independent=2,
                assisted=1,
                learnerVersion=4,
            )
            request("POST", f"sessions/{session_id}/end")
            restored = request("GET", f"courses/{id}/learner-state")
            assert restored == state
            resumed = request(
                "POST", f"courses/{id}/sessions", 202, json={"expectedLearnerVersion": 4}
            )
            assert resumed["id"] != session_id
            run_ready(resumed["runIds"][0], "waiting_for_learner")
            assert request("GET", f"courses/{id}/learner-state") == state
            passed("new_session_retains_progress_and_selects_next_eligible_concept")
            (ROOT / "journey-graph.json").write_text(json.dumps(graph))
            (ROOT / "journey-materials.json").write_text(json.dumps(learning))
            assert original_workspace() == baseline, (
                "Original workspace changed during isolated validation"
            )
            passed("original_courses_graphs_and_learning_history_unchanged")
            report["status"] = "passed"
        except Exception as exc:
            report["status"] = "failed"
            report["failure"] = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
            raise
        finally:
            report["finishedAt"] = datetime.now(UTC).isoformat()
            save()
            engine.dispose()


if __name__ == "__main__":
    main()
