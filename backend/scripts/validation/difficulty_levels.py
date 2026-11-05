"""Real-service difficulty validation in an isolated, disposable SQLite database."""

import hashlib
import json
import re
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from learnloop.api import create_app
from learnloop.core.config import get_settings
from learnloop.core.domain import chunk_id
from learnloop.persistence.database import (
    Activity,
    Chunk,
    Course,
    Document,
    LearnerState,
    Run,
    session_factory,
)
from learnloop.runtime.events import new_run
from learnloop.runtime.worker import work_once
from learnloop.services.clients import Services
from scripts.development.local_sandbox import local_stack

MATERIAL = """Total price for a fixed fee and unit charge.
Use T = F + p*q, where T is total price, F is a fixed fee, p is price per unit,
and q is quantity. F and p are nonnegative; q is a nonnegative integer.
The fixed fee does not depend on quantity; the variable charge is p*q.
At zero quantity the total is F. Increasing quantity by one adds p to the total.
For a hypothetical offer with F=5, p=2 and q=3, T=5+2*3=11.
Compare two offers by calculating both totals at the same quantity.
For a second hypothetical offer with F=8 and p=1, quantity 3 also costs 11.
At quantity 8 the first offer costs 21 and the second costs 16, so the second
is cheaper at that quantity. Equal totals at one quantity do not establish that
the offers have equal totals at every quantity. These examples exclude taxes,
discounts and other fees. Use only this formula and the stated assumptions.
"""


def fingerprint(factory):
    with factory() as db:
        data = {
            "documents": [
                (d.id, d.graph) for d in db.scalars(select(Document).order_by(Document.id))
            ],
            "learners": [
                (s.id, s.version, s.evidence)
                for s in db.scalars(select(LearnerState).order_by(LearnerState.id))
            ],
            "activities": [
                (a.id, a.status, a.public, a.private)
                for a in db.scalars(select(Activity).order_by(Activity.id))
            ],
        }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def main(validation_name="difficulty-validation", exercise_plans=False):
    settings = get_settings()
    main_factory = session_factory(settings)
    before = fingerprint(main_factory)
    schema = "ll_difficulty_" + uuid4().hex
    assert re.fullmatch(r"ll_difficulty_[0-9a-f]{32}", schema)
    assert re.fullmatch(r"[a-z-]+", validation_name)
    root = Path(__file__).resolve().parents[3] / "tmp" / validation_name
    root.mkdir(parents=True, exist_ok=True)
    report = {"schema": schema, "levels": {}, "status": "running"}

    def save():
        (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    class ObservedServices(Services):
        def generate(self, role, instruction, context, output):
            print(
                json.dumps({"role": role, "schema": output.__name__, "event": "start"}), flush=True
            )
            result = super().generate(role, instruction, context, output)
            if output.__name__ == "GroundingReview":
                print(
                    json.dumps({"schema": output.__name__, "review": result.model_dump()}),
                    flush=True,
                )
            return result

    resources = ExitStack()
    temporary_settings, factory, services = resources.enter_context(
        local_stack(
            settings.model_copy(update={"local_owner_id": "difficulty-validation-" + uuid4().hex}),
            ObservedServices,
        )
    )
    course_id, document_id = str(uuid4()), str(uuid4())
    concept_id = document_id + ":total-price"
    passage_id = chunk_id(document_id, 0)
    save()
    try:
        with factory.begin() as db:
            course = Course(
                id=course_id,
                owner_id=temporary_settings.local_owner_id,
                title="Difficulty validation",
            )
            db.add(course)
            db.flush()
            db.add(LearnerState(course_id=course_id, owner_id=course.owner_id))
            db.add(
                Document(
                    id=document_id,
                    course_id=course_id,
                    filename="pricing.txt",
                    content_type="text/plain",
                    content=MATERIAL.encode(),
                    sha256=hashlib.sha256(MATERIAL.encode()).hexdigest(),
                    status="published",
                    pages=1,
                    graph={
                        "concepts": [
                            {
                                "id": concept_id,
                                "title": "Calculate and compare total prices",
                                "summary": "Use a fixed fee plus a per-unit charge to calculate and compare total prices at the same quantity.",
                                "targetDifficulty": "intermediate",
                                "sources": [{"chunkId": passage_id, "quote": MATERIAL[:120]}],
                            }
                        ],
                        "prerequisites": [],
                    },
                )
            )
            db.flush()
            db.add(
                Chunk(
                    id=passage_id,
                    document_id=document_id,
                    course_id=course_id,
                    ordinal=0,
                    page=1,
                    text=MATERIAL,
                )
            )
            db.flush()
            run_id = new_run(db, course, "course_preparation", {"document_id": document_id}).id
        services.index(
            [
                {
                    "id": passage_id,
                    "document_id": document_id,
                    "course_id": course_id,
                    "text": MATERIAL,
                }
            ],
            temporary_settings.local_owner_id,
        )
        assert work_once(factory, services)
        with factory() as db:
            run = db.get(Run, run_id)
            assert run.snapshot["status"] == "completed", (
                run.snapshot.get("error"),
                run.input.get("failureDiagnostics"),
            )
        with TestClient(create_app(temporary_settings, factory, services)) as client:
            client.headers["Authorization"] = "Bearer " + settings.api_token.get_secret_value()
            material = client.get(f"/api/courses/{course_id}/materials").json()["materials"][0]
            assert material["questionCountsByDifficulty"] == {
                "basic": 2,
                "intermediate": 2,
                "advanced": 2,
            }
            assert "correctChoiceId" not in str(material)
            report["questionCounts"] = material["questionCountsByDifficulty"]
            assert set(material["lessonsByDifficulty"]) == {"basic", "intermediate", "advanced"}
            report["lessonLevels"] = sorted(material["lessonsByDifficulty"])
            for level in ("basic", "intermediate", "advanced"):
                state = client.get(f"/api/courses/{course_id}/learner-state").json()
                client.post(
                    f"/api/courses/{course_id}/concepts/{concept_id}/target",
                    json={"targetDifficulty": level, "expectedLearnerVersion": state["version"]},
                ).raise_for_status()
                state = client.get(f"/api/courses/{course_id}/learner-state").json()
                if exercise_plans:
                    plan = client.get(f"/api/courses/{course_id}/plan").json()
                    client.post(
                        f"/api/courses/{course_id}/plan/revise",
                        json={
                            "operationId": f"{level}-goal",
                            "expectedPlanVersion": plan["version"],
                            "expectedLearnerVersion": state["version"],
                            "goal": {
                                "description": "Calculate and compare total prices independently.",
                                "conceptIds": [concept_id],
                            },
                        },
                    ).raise_for_status()
                session = client.post(
                    f"/api/courses/{course_id}/sessions",
                    json={"expectedLearnerVersion": state["version"]},
                ).json()
                assert work_once(factory, services)
                for index in range(2):
                    activity = client.get(f"/api/sessions/{session['id']}").json()["activity"]
                    assert activity and activity["difficulty"] == level
                    with factory() as db:
                        saved = db.get(Activity, activity["id"])
                        answer = saved.private["correctChoiceId"]
                        reference_answer = saved.private["question"].get("referenceAnswer")
                        if exercise_plans:
                            assert saved.private["question"]["rubric"] and reference_answer
                    if exercise_plans:
                        client.post(f"/api/activities/{activity['id']}/present").raise_for_status()
                    state = client.get(f"/api/courses/{course_id}/learner-state").json()
                    client.post(
                        f"/api/activities/{activity['id']}/responses",
                        json={
                            "operationId": f"{level}-{index}",
                            "expectedLearnerVersion": state["version"],
                            "choiceId": answer,
                            **(
                                {"reasoning": reference_answer}
                                if exercise_plans and index == 1
                                else {}
                            ),
                        },
                    ).raise_for_status()
                    assert work_once(factory, services)
                    state = client.get(f"/api/courses/{course_id}/learner-state").json()
                    if exercise_plans:
                        current = client.get(f"/api/sessions/{session['id']}").json()
                        assessment = current["assessment"]
                        assert (
                            assessment
                            and assessment["rubricScore"] == 1
                            and assessment["rubricCoverage"]
                        ), current
                        assert assessment["timing"]["basis"] == "presentation"
                        assert assessment["timing"]["responseTimeMs"] is not None
                        assert current["plan"]["selected"]["conceptId"] == concept_id
                        assert current["plan"]["candidates"] and activity["rationale"]
                        report.setdefault("planningAndAssessment", []).append(
                            {
                                "difficulty": level,
                                "action": activity["action"],
                                "planVersion": current["plan"]["version"],
                                "rubricScore": assessment["rubricScore"],
                                "criterionCount": len(assessment["rubricCoverage"]),
                                "writtenReasoning": index == 1,
                                "responseTimeRecorded": True,
                            }
                        )
                    assert state["overallStates"][concept_id] == (
                        "developing" if index == 0 else "demonstrated"
                    ), state
                    if index == 0:
                        client.post(
                            f"/api/sessions/{session['id']}/next",
                            json={"expectedLearnerVersion": state["version"]},
                        ).raise_for_status()
                        assert work_once(factory, services)
                report["levels"][level] = {
                    "assigned": 2,
                    "independentEvidence": 2,
                    "state": state["concepts"][concept_id][level]["state"],
                }
                save()
                client.post(f"/api/sessions/{session['id']}/end").raise_for_status()
        report["existingDataUnchanged"] = fingerprint(main_factory) == before
        assert report["existingDataUnchanged"]
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        resources.close()
        main_factory.kw["bind"].dispose()
        report["temporaryDataRemoved"] = True
        save()
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
