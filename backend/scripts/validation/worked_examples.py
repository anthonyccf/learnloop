"""Upgrade existing examples and verify the rest of the course stays unchanged."""

import argparse
import copy
import json

import httpx
from sqlalchemy import select

from learnloop.agents.expert.materials import MATERIALS_VERSION
from learnloop.core.config import get_settings
from learnloop.core.schemas import PostExample
from learnloop.persistence.database import Document, LearnerState, session_factory
from scripts.paths import ARTIFACT_ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id")
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    path = ARTIFACT_ROOT / f"worked-examples-{args.document_id}.json"
    with session_factory()() as db:
        doc = db.get(Document, args.document_id)
        graph = copy.deepcopy(doc.graph)
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == doc.course_id))
        snapshot = {"graph": graph, "evidence": state.evidence, "learnerVersion": state.version}
    with httpx.Client(
        base_url="http://127.0.0.1:8010/api/",
        headers={"Authorization": "Bearer " + get_settings().api_token.get_secret_value()},
        trust_env=False,
    ) as client:
        if args.start:
            if path.exists():
                raise RuntimeError("Keep the existing before-state.")
            path.write_text(json.dumps(snapshot, indent=2))
            receipt = client.post(f"documents/{args.document_id}/materials", json={})
            receipt.raise_for_status()
            snapshot["receipt"] = receipt.json()
            path.write_text(json.dumps(snapshot, indent=2))
            print(json.dumps(receipt.json()))
            return
        before = json.loads(path.read_text())
        run = client.get(f"agent-activity/runs/{before['receipt']['runId']}").json()
        resources = graph["resources"]
        count = sum(r.get("version") == MATERIALS_VERSION for r in resources.values())
        print(
            json.dumps(
                {
                    "status": run["status"],
                    "updated": count,
                    "total": len(resources),
                    "summary": run["summary"],
                }
            )
        )
        for id, resource in resources.items():
            prior = before["graph"]["resources"][id]
            assert resource["tests"] == prior["tests"]
            assert {k: v for k, v in resource["lesson"].items() if k != "workedExample"} == {
                k: v for k, v in prior["lesson"].items() if k != "workedExample"
            }
            if resource.get("version") == MATERIALS_VERSION:
                PostExample.model_validate(resource["lesson"]["workedExample"])
        assert {k: v for k, v in graph.items() if k != "resources"} == {
            k: v for k, v in before["graph"].items() if k != "resources"
        }
        assert (
            snapshot["evidence"] == before["evidence"]
            and snapshot["learnerVersion"] == before["learnerVersion"]
        )
        if count == len(resources):
            print(
                "Verified: all examples upgraded; lesson prose, private tests, graph and learner progress unchanged."
            )


if __name__ == "__main__":
    main()
