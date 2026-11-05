"""Opt-in live smoke test. Uses synthetic text, a temporary SQLite file and local vectors."""

import argparse
import json
from contextlib import ExitStack
from uuid import uuid4

from fastapi.testclient import TestClient

from learnloop.api import create_app
from learnloop.core.config import get_settings
from learnloop.persistence.database import Activity
from learnloop.runtime.worker import work_once
from scripts.development.local_sandbox import local_stack


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured embedding and generation services using synthetic learning material",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to run external service checks.")
    resources = ExitStack()
    settings, factory, services = resources.enter_context(local_stack(get_settings()))
    try:
        with TestClient(create_app(settings, factory, services)) as client:
            client.headers["Authorization"] = "Bearer " + settings.api_token.get_secret_value()

            def checked(response, expected=200):
                if response.status_code != expected:
                    raise RuntimeError(f"Smoke API request failed with HTTP {response.status_code}")
                return response.json()

            def process(run_id, expected):
                assert work_once(factory, services), "No queued job found"
                run = checked(client.get(f"/api/agent-activity/runs/{run_id}"))
                print(
                    json.dumps(
                        {
                            "workflow": run["workflow"],
                            "status": run["status"],
                            "events": run["lastSequence"],
                            "summary": run["summary"],
                        }
                    ),
                    flush=True,
                )
                if run["status"] != expected:
                    raise RuntimeError(
                        "Live workflow did not reach the expected state. See its safe summary above."
                    )
                return run

            course = checked(
                client.post("/api/courses", json={"title": "Synthetic backend smoke test"}),
                201,
            )
            material = b"Gradient descent minimizes a loss function by subtracting a positive learning rate times its gradient from the model parameters. The gradient points in the direction of steepest local increase. Moving in the opposite direction can reduce the loss for a sufficiently small step. The learning rate controls step size. A very large learning rate may overshoot the minimum or diverge. A very small learning rate can converge slowly. These facts describe introductory gradient descent and do not guarantee convergence for every loss function."
            upload = checked(
                client.post(
                    f"/api/courses/{course['id']}/documents",
                    files={"file": ("synthetic-notes.txt", material, "text/plain")},
                ),
                202,
            )
            process(upload["runId"], "completed")
            found = checked(
                client.post(
                    f"/api/courses/{course['id']}/search",
                    json={"query": "How does the learning rate control gradient descent?"},
                )
            )
            assert found["passages"], "Published source retrieval returned no passages"
            session = checked(
                client.post(
                    f"/api/courses/{course['id']}/sessions",
                    json={"expectedLearnerVersion": 0},
                ),
                202,
            )
            process(session["runIds"][0], "waiting_for_learner")
            current = checked(client.get(f"/api/sessions/{session['id']}"))["activity"]
            assert "correctChoiceId" not in json.dumps(current)
            with factory() as db:
                # Test harness only: use the private key to submit one known-correct response.
                answer = db.get(Activity, current["id"]).private["correctChoiceId"]
            submission = checked(
                client.post(
                    f"/api/activities/{current['id']}/responses",
                    json={
                        "operationId": str(uuid4()),
                        "expectedLearnerVersion": 0,
                        "choiceId": answer,
                    },
                ),
                202,
            )
            process(submission["runId"], "waiting_for_learner")
            assessment = checked(client.get(f"/api/submissions/{submission['submissionId']}"))
            assert (
                assessment["status"] == "assessed"
                and assessment["assessment"]["learnerVersion"] == 1
            )
            state = checked(client.get(f"/api/courses/{course['id']}/learner-state"))
            assert state["version"] == 1
            print(
                json.dumps(
                    {
                        "live_smoke": "passed",
                        "learnerVersion": state["version"],
                        "private_answer_key_exposed": False,
                    }
                ),
                flush=True,
            )
    finally:
        resources.close()
        print("Synthetic SQLite records and local vectors cleaned up.", flush=True)


if __name__ == "__main__":
    main()
