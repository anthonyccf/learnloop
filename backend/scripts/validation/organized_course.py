"""Run and verify a real course organization upgrade without changing learning evidence.

Usage: python -m scripts.validation.organized_course COURSE_ID --start
Then: python -m scripts.validation.organized_course COURSE_ID
Writes local structural verification results, never credentials or test answers.
"""

import argparse
import hashlib
import json

import httpx
from sqlalchemy import select

from learnloop.core.config import get_settings
from learnloop.core.domain import validate_graph
from learnloop.persistence.database import Document, LearnerState, session_factory
from scripts.paths import ARTIFACT_ROOT


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("course_id")
    parser.add_argument("--start", action="store_true")
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Retry organization while retaining the original verification baseline",
    )
    args = parser.parse_args()
    path = ARTIFACT_ROOT / f"organization-check-{args.course_id}.json"
    settings, factory = get_settings(), session_factory()
    with factory() as db:
        docs = list(
            db.scalars(
                select(Document)
                .where(Document.course_id == args.course_id, Document.status == "published")
                .order_by(Document.id)
            )
        )
        concepts = [c for doc in docs for c in doc.graph["concepts"]]
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == args.course_id))
        baseline = {
            "conceptIds": sorted(c["id"] for c in concepts),
            "evidence": digest(state.evidence),
            "learnerVersion": state.version,
            "resources": {d.id: digest(d.graph.get("resources", {})) for d in docs},
        }
    with httpx.Client(
        base_url="http://127.0.0.1:8010/api/",
        headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()},
        trust_env=False,
    ) as client:
        if args.start:
            if path.exists():
                raise RuntimeError(
                    "Verification baseline already exists; reuse it rather than overwriting before-state."
                )
            response = client.post(f"courses/{args.course_id}/organize", json={})
            response.raise_for_status()
            baseline["receipt"] = response.json()
            path.write_text(json.dumps(baseline, indent=2))
            print(json.dumps(response.json()))
            return
        before = json.loads(path.read_text())
        if args.retry:
            response = client.post(f"courses/{args.course_id}/organize", json={})
            response.raise_for_status()
            before["receipt"] = response.json()
            path.write_text(json.dumps(before, indent=2))
            print(json.dumps(response.json()))
            return
        receipt = before["receipt"]
        if "runId" in receipt:
            run = client.get(f"agent-activity/runs/{receipt['runId']}").json()
            print(json.dumps({"status": run["status"], "summary": run["summary"]}))
            if run["status"] != "completed":
                return
        graph = client.get(f"courses/{args.course_id}").json()["graph"]
        validate_graph(graph)
        members = [id for t in graph["topics"] for id in t["conceptIds"]]
        assert sorted(members) == before["conceptIds"]
        for field in ("conceptIds", "evidence", "learnerVersion", "resources"):
            assert baseline[field] == before[field], f"Unexpected change to {field}"
        assert graph["organization"]["reviewed"]
        # A complete map includes every concept; connectedness is measured, not forced.
        neighbors = {id: set() for id in members}
        for e in graph["prerequisites"]:
            neighbors[e["prerequisite"]].add(e["dependent"])
            neighbors[e["dependent"]].add(e["prerequisite"])
        for e in graph["related"]:
            neighbors[e["first"]].add(e["second"])
            neighbors[e["second"]].add(e["first"])
        components, seen = 0, set()
        for id in members:
            if id in seen:
                continue
            components += 1
            queue = [id]
            while queue:
                current = queue.pop()
                if current in seen:
                    continue
                seen.add(current)
                queue.extend(neighbors[current] - seen)
        report = {
            "concepts": len(members),
            "topics": len(graph["topics"]),
            "prerequisites": len(graph["prerequisites"]),
            "related": len(graph["related"]),
            "connectedComponentsIncludingRelated": components,
            "ungrouped": 0,
            "duplicateConcepts": len(members) - len(set(members)),
            "acyclic": True,
            "evidenceUnchanged": True,
            "lessonsAndTestsUnchanged": True,
            "reviewedPassages": sum(
                d.graph.get("coverage", {}).get("processedPassages", 0) for d in docs
            ),
            "totalPassages": sum(d.graph.get("coverage", {}).get("totalPassages", 0) for d in docs),
            "topicTitles": [t["title"] for t in graph["topics"]],
        }
        path.with_suffix(".result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
