"""Revalidate saved legacy lessons against current scopes, then publish releases.

Uses the configured model for missing reviews; does not regenerate lessons or
reset learner state. Content-bound checkpoints make interrupted reviews reusable.
"""

import argparse
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock
from pydantic import BaseModel
from sqlalchemy import select

from learnloop.agents.expert.curriculum import validate_curriculum
from learnloop.agents.expert.materials import difficulty_complete, material_valid
from learnloop.agents.expert.organization import current_organization
from learnloop.core.config import ROOT, get_settings
from learnloop.core.schemas import LessonScopeReview
from learnloop.persistence.database import Chunk, Course, Document, session_factory
from learnloop.persistence.releases import fingerprint, publish_course, scope_fingerprint
from learnloop.services.clients import Services
from scripts.paths import ARTIFACT_ROOT


class ScopeReview(BaseModel):
    conceptId: str
    accepted: bool
    feedback: str


class BatchReview(BaseModel):
    reviews: list[ScopeReview]


SCOPE_PROMPT = (
    "Independently audit each supplied saved lesson against its assigned objective and "
    "the full course teaching-scope catalog. Return exactly one review per lesson. "
    "Accept only if the lesson teaches the assigned objective and planned capability. "
    "Reject substantial reteaching of another objective's exclusive scope. Brief "
    "prerequisite reminders, applying foundations in a new problem, shared notation "
    "and references back to earlier lessons are allowed. Do not demand standalone "
    "explanations of prerequisites. Judge the actual content, not the presence of an "
    "earlier review. Give concrete feedback for any rejection."
)


def repair_course(factory, services, course_id):
    with factory() as db:
        docs = list(db.scalars(select(Document).where(Document.course_id == course_id)))
        concepts = [c for d in docs for c in d.graph.get("concepts", [])]
        organization = current_organization(docs, concepts)
        if not organization:
            raise ValueError("Review the course organization before migrating its release")
        objectives = {
            id: item
            for d in docs
            for id, item in d.graph.get("curriculum", {}).get("objectives", {}).items()
        }
        validate_curriculum(
            {"objectives": list(objectives.values())}, concepts, organization["prerequisites"]
        )
        chunks = {
            c.id: {"text": c.text}
            for c in db.scalars(select(Chunk).where(Chunk.course_id == course_id))
        }
        catalog = [{"id": c["id"], "title": c["title"], **objectives[c["id"]]} for c in concepts]
        lessons = []
        for doc in docs:
            for concept in doc.graph.get("concepts", []):
                id = concept["id"]
                pack = doc.graph["resources"][id]
                if not material_valid(pack, chunks) or not difficulty_complete(pack):
                    raise ValueError(
                        "Existing resources must pass source and difficulty checks first"
                    )
                expected = scope_fingerprint(pack["lesson"], objectives[id])
                if pack.get("scopeFingerprint") != expected or not pack.get("scopeReview", {}).get(
                    "accepted"
                ):
                    lessons.append(
                        {
                            "conceptId": id,
                            "documentId": doc.id,
                            "curriculum": objectives[id],
                            "lesson": copy.deepcopy(pack["lesson"]),
                            "fingerprint": expected,
                        }
                    )
        stale_curriculum = any(
            d.graph["curriculum"].get("signature") != organization["signature"] for d in docs
        )
    print(
        f"Course {course_id}: {len(lessons)} saved lessons need current scope receipts", flush=True
    )
    report_path = ARTIFACT_ROOT / f"legacy-release-review-{course_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(report_path.read_text()) if report_path.exists() else {"reviews": {}}
    context_hash = fingerprint({"catalog": catalog, "organization": organization})
    if report.get("contextHash") != context_hash:
        report = {"contextHash": context_hash, "reviews": {}}

    def save():
        report_path.write_text(json.dumps(report, indent=2))

    if stale_curriculum:
        review = report.get("curriculumReview")
        if not review or not review["accepted"]:
            review = services.generate(
                "Expert",
                "Independently audit this existing curriculum against the current course concepts "
                "and reviewed prerequisite graph. Accept only if every objective still teaches "
                "its named concept, exclusive scopes are coherent, assumed prerequisites match "
                "the graph, and the assigned layers are pedagogically defensible. Curriculum "
                "scope descriptions are concise planning metadata, not complete lessons: they "
                "need not repeat every source fact, example number or implementation detail. "
                "Those details are checked in the separate lesson review. Judge whether the "
                "scope assigns the correct capability, not whether it fully explains it. Return accepted "
                "and concrete feedback. Do not invent a replacement plan.",
                {
                    "concepts": concepts,
                    "curriculum": catalog,
                    "prerequisites": organization["prerequisites"],
                    "previousReview": review,
                },
                LessonScopeReview,
            ).model_dump()
            report["curriculumReview"] = review
            save()
        if not review["accepted"]:
            raise ValueError("Current curriculum requires repair: " + review["feedback"])
        with factory.begin() as db:
            current_docs = list(db.scalars(select(Document).where(Document.course_id == course_id)))
            current = current_organization(
                current_docs, [c for d in current_docs for c in d.graph.get("concepts", [])]
            )
            if not current or current["signature"] != organization["signature"]:
                raise ValueError("Course changed during curriculum review")
            for doc in current_docs:
                graph = copy.deepcopy(doc.graph)
                graph["curriculum"]["signature"] = organization["signature"]
                graph["curriculum"]["compatibilityReview"] = review
                graph["curriculum"]["compatibilityFingerprint"] = context_hash
                doc.graph = graph

    def review_batch(batch):
        cached = [report["reviews"].get(item["conceptId"]) for item in batch]
        if all(
            r and r.get("fingerprint") == item["fingerprint"]
            for r, item in zip(cached, batch, strict=True)
        ):
            return batch, cached
        result = services.generate(
            "Expert",
            SCOPE_PROMPT,
            {
                "courseCatalog": catalog,
                "lessons": [
                    {k: v for k, v in item.items() if k not in ("documentId", "fingerprint")}
                    for item in batch
                ],
            },
            BatchReview,
        )
        expected = {item["conceptId"] for item in batch}
        if len(result.reviews) != len(batch) or {r.conceptId for r in result.reviews} != expected:
            raise ValueError("The scope reviewer returned incomplete or invented lesson IDs")
        by_id = {r.conceptId: r.model_dump() for r in result.reviews}
        return batch, [
            {**by_id[item["conceptId"]], "fingerprint": item["fingerprint"]} for item in batch
        ]

    rejected = []
    batches = [lessons[start : start + 8] for start in range(0, len(lessons), 8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(review_batch, batch) for batch in batches]
        for future in as_completed(futures):
            batch, reviews = future.result()
            with factory.begin() as db:
                for item, review in zip(batch, reviews, strict=True):
                    report["reviews"][item["conceptId"]] = review
                    if not review["accepted"]:
                        rejected.append(item["conceptId"])
                        continue
                    doc = db.get(Document, item["documentId"])
                    graph = copy.deepcopy(doc.graph)
                    pack = graph["resources"][item["conceptId"]]
                    objective = graph["curriculum"]["objectives"][item["conceptId"]]
                    if scope_fingerprint(pack["lesson"], objective) != item["fingerprint"]:
                        raise ValueError("Lesson or scope changed during review")
                    pack.setdefault("previousScopeReview", copy.deepcopy(pack.get("scopeReview")))
                    pack["scopeReview"] = {"accepted": True, "feedback": review["feedback"]}
                    pack["scopeFingerprint"] = item["fingerprint"]
                    doc.graph = graph
                    # Next item may be from the same document; retain earlier updates.
                    db.flush()
            save()
            print(
                f"Course {course_id}: reviewed {len(report['reviews'])}/{len(lessons)} lessons",
                flush=True,
            )
    if rejected:
        raise ValueError(f"{len(rejected)} lessons require content repair; see the review report")
    with factory.begin() as db:
        release = publish_course(db, course_id)
        print(f"Course {course_id}: published release {release.version}", flush=True)
        report["releaseId"] = release.id
    save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    settings = get_settings()
    if not settings.uses_sqlite:
        raise SystemExit("This repair expects the migrated SQLite workspace")
    factory = session_factory(settings)
    services = Services(settings)
    path = Path(factory.kw["bind"].url.database)
    with FileLock(str(path) + ".worker.lock", timeout=0):
        backup = (
            ROOT
            / "data"
            / ("before-legacy-review-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".db")
        )
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        with factory() as db:
            ids = list(
                db.scalars(select(Course.id).where(Course.owner_id == settings.local_owner_id))
            )
        for id in ids:
            repair_course(factory, services, id)


if __name__ == "__main__":
    main()
