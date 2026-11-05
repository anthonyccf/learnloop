"""Upgrade saved lessons and verify brevity/structure without changing test banks."""

import argparse
import hashlib
import json
import re

import httpx
from sqlalchemy import select

from learnloop.core.config import get_settings
from learnloop.persistence.database import Document, LearnerState, session_factory
from scripts.paths import ARTIFACT_ROOT


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def metrics(lessons):
    words, sentences, bullet_counts = [], [], []
    for lesson in lessons.values():
        text = lesson["explanation"]
        words.append(len(text.split()))
        sentences.extend(
            len(part.split()) for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()
        )
        bullet_counts.append(len(re.findall(r"^- ", text, re.M)))
    return {
        "meanBodyWords": round(sum(words) / len(words), 1),
        "meanSentenceWords": round(sum(sentences) / len(sentences), 1),
        "minimumBullets": min(bullet_counts),
        "maximumBullets": max(bullet_counts),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id")
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    settings, factory = get_settings(), session_factory()
    path = ARTIFACT_ROOT / f"learning-post-check-{args.document_id}.json"
    with factory() as db:
        doc = db.get(Document, args.document_id)
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == doc.course_id))
        resources = doc.graph["resources"]
        lessons = {id: r["lesson"] for id, r in resources.items()}
        snapshot = {
            "lessons": lessons,
            "testsHash": digest({id: r["tests"] for id, r in resources.items()}),
            "graphHash": digest(
                {key: doc.graph.get(key) for key in ("concepts", "prerequisites", "organization")}
            ),
            "evidenceHash": digest(state.evidence),
            "learnerVersion": state.version,
        }
    with httpx.Client(
        base_url="http://127.0.0.1:8010/api/",
        headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()},
        trust_env=False,
    ) as client:
        if args.start:
            if path.exists():
                raise RuntimeError("Keep the existing before-state; do not overwrite it.")
            response = client.post(f"documents/{args.document_id}/materials", json={})
            response.raise_for_status()
            snapshot["receipt"] = response.json()
            path.write_text(json.dumps(snapshot, indent=2))
            print(json.dumps(response.json()))
            return
        before = json.loads(path.read_text())
        for field in ("testsHash", "graphHash", "evidenceHash", "learnerVersion"):
            assert snapshot[field] == before[field], f"Unexpected change: {field}"
        complete = sum(r.get("version") == 2 for r in resources.values())
        run = client.get(f"agent-activity/runs/{before['receipt']['runId']}").json()
        print(
            json.dumps(
                {
                    "status": run["status"],
                    "updated": complete,
                    "total": len(lessons),
                    "summary": run["summary"],
                }
            )
        )
        if complete != len(lessons) or run["status"] != "completed":
            return
        result = {
            "lessonsRewritten": complete,
            "before": metrics(before["lessons"]),
            "after": metrics(lessons),
            "testsUnchanged": True,
            "graphUnchanged": True,
            "progressUnchanged": True,
        }
        assert result["after"]["minimumBullets"] >= 3 and result["after"]["maximumBullets"] <= 6
        result["bodyWordReductionPercent"] = round(
            100 * (1 - result["after"]["meanBodyWords"] / result["before"]["meanBodyWords"])
        )
        path.with_suffix(".result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        print("First lesson preview:\n" + next(iter(lessons.values()))["explanation"])


if __name__ == "__main__":
    main()
