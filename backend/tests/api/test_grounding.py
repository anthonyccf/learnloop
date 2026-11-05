from tests.release_fixtures import seed_legacy_release
import copy

import pytest
from sqlalchemy import func, select

from learnloop.core.schemas import Assessment, ExtendedTopicReview, GroundingReview, PostMaterials
from learnloop.persistence.database import Activity, Chunk, Document, Submission
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare
from tests.conftest import COURSE_TEXT


def start(stack, course_id):
    client, factory, services, _ = stack
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    assert work_once(factory, services)
    return client.get(f"/api/sessions/{session['id']}").json()


def test_expert_extension_is_labelled_and_can_be_answered(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    generate = services.generate

    def approve_extension(role, instruction, context, output):
        if output is ExtendedTopicReview:
            assert role == "Expert"
            return ExtendedTopicReview(
                approved=True,
                reason="Additional optimization context helps connect the lecture's core ideas.",
            )
        return generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", approve_extension)
    services.grounding_status = "uncertain"
    session = start(stack, course_id)
    activity = session["activity"]
    assert activity["extendedTopic"] is True
    assert "Additional optimization" in activity["extensionReason"]
    assert "correctChoiceId" not in activity
    with factory() as db:
        saved = db.get(Activity, activity["id"])
        assert saved.private["grounding"]["status"] == "extended"
        choice = saved.private["correctChoiceId"]
    response = client.post(
        f"/api/activities/{activity['id']}/responses",
        json={"operationId": "extended-answer", "expectedLearnerVersion": 0, "choiceId": choice},
    )
    assert response.status_code == 202
    assert work_once(factory, services)
    assessed = client.get(f"/api/sessions/{session['id']}").json()
    assert assessed["activity"]["extendedTopic"] is True
    assert assessed["activity"]["status"] == "assessed"
    assert assessed["assessment"]["correct"] is True


@pytest.mark.parametrize("status", ["unsupported", "uncertain"])
def test_semantic_failure_blocks_graph_publication(stack, status):
    client, factory, services, _ = stack
    services.grounding_status = status
    course_id = client.post("/api/courses", json={"title": "Grounding review"}).json()["id"]
    upload = client.post(
        f"/api/courses/{course_id}/documents", files={"file": ("notes.txt", COURSE_TEXT.encode())}
    ).json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{upload['runId']}").json()
    assert run["status"] == "needs_review"
    assert client.get(f"/api/courses/{course_id}").json()["graph"]["concepts"] == []
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0


@pytest.mark.parametrize("bad_id", [True, False])
def test_invalid_materials_are_flagged_before_saving_or_serving(stack, monkeypatch, bad_id):
    client, factory, services, _ = stack
    generate = services.generate

    def fail_material(role, instruction, context, output):
        result = generate(role, instruction, context, output)
        if issubclass(output, PostMaterials) and bad_id:
            result.tests[1].sources[0].chunkId = "foreign-course-chunk"
        if output is GroundingReview and "lesson" in context["item"] and not bad_id:
            result.status = "unsupported"
        return result

    monkeypatch.setattr(services, "generate", fail_material)
    course_id = client.post("/api/courses", json={"title": "Material review"}).json()["id"]
    upload = client.post(
        f"/api/courses/{course_id}/documents", files={"file": ("notes.txt", COURSE_TEXT.encode())}
    ).json()
    assert work_once(factory, services)
    assert (
        client.get(f"/api/agent-activity/runs/{upload['runId']}").json()["status"] == "needs_review"
    )
    with factory() as db:
        graph = db.get(Document, upload["documentId"]).graph
        assert not graph.get("resources")
        assert graph["sourceIssues"]
    assert client.get(f"/api/courses/{course_id}/materials").json()["materials"] == []
    review = client.get(f"/api/documents/{upload['documentId']}/review").json()
    assert "correctChoiceId" not in str(review)


def test_saved_question_requires_support_and_cannot_create_activity_on_rejection(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    services.grounding_status = "unsupported"
    session = start(stack, course_id)
    assert session["activity"] is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Activity)) == 0
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0


def test_assignment_reviews_question_without_rechecking_unrelated_catalog_claims(
    stack, monkeypatch
):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    generate = services.generate
    reviewed = []

    def review_question(role, instruction, context, output):
        result = generate(role, instruction, context, output)
        if output is GroundingReview:
            reviewed.append(context["item"])
            if "concept" in context["item"]:
                result.status = "unsupported"
                result.summary = "The topic summary includes an unrelated claim."
        return result

    monkeypatch.setattr(services, "generate", review_question)
    session = start(stack, course_id)
    assert session["activity"]
    assert len(reviewed) == 1
    assert {"prompt", "correctChoiceId", "explanation", "hint", "rubric", "sources"} <= reviewed[
        0
    ].keys()
    assert "concept" not in reviewed[0]
    # Assignment does not manufacture learner evidence.
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 0


def test_fallback_question_with_bad_passage_id_is_not_assigned(stack):
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        for pack in graph["resources"].values():
            pack["tests"] = []
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    services.bad_source = True
    assert start(stack, course_id)["activity"] is None


@pytest.mark.parametrize("failure", ["missing_legacy_sources", "changed_passage", "unpublished"])
def test_assessment_uses_frozen_sources_and_rejects_missing_legacy_evidence(stack, failure):
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    session = start(stack, course_id)
    activity_id = session["activity"]["id"]
    with factory.begin() as db:
        activity = db.get(Activity, activity_id)
        if failure == "missing_legacy_sources":
            activity.private = {
                k: v for k, v in activity.private.items() if k not in ("question", "grounding")
            }
            activity.public = {**activity.public, "sources": []}
        elif failure == "changed_passage":
            db.scalar(
                select(Chunk).where(Chunk.document_id == upload["documentId"])
            ).text = "An unrelated replacement passage."
        else:
            db.get(Document, upload["documentId"]).status = "needs_review"
    services.grounding_status = "unsupported"
    response = client.post(
        f"/api/activities/{activity_id}/responses",
        json={
            "operationId": "source-check",
            "expectedLearnerVersion": 0,
            "choiceId": "a",
        },
    ).json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{response['runId']}").json()
    state = client.get(f"/api/courses/{course_id}/learner-state").json()
    if failure == "missing_legacy_sources":
        assert run["status"] == "needs_review"
        assert state["version"] == 0 and state["concepts"] == {}
        with factory() as db:
            assert db.get(Submission, response["submissionId"]).assessment == {}
    else:
        # Mutable preparation changes cannot invalidate previously released evidence.
        assert run["status"] == "waiting_for_learner" and state["version"] == 1


def test_current_receipt_avoids_duplicate_review_and_private_data_stays_private(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    activity = start(stack, course_id)["activity"]
    assert not {"question", "grounding", "correctChoiceId"} & activity.keys()
    # A fresh semantic call would reject, so successful assessment establishes cache reuse.
    services.grounding_status = "unsupported"
    response = client.post(
        f"/api/activities/{activity['id']}/responses",
        json={
            "operationId": "review-once",
            "expectedLearnerVersion": 0,
            "choiceId": "a",
        },
    ).json()
    assert work_once(factory, services)
    assert client.get(f"/api/submissions/{response['submissionId']}").json()["status"] == "assessed"


def test_legacy_materials_require_review_and_revalidation_preserves_tests(stack):
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        for pack in graph["resources"].values():
            pack.pop("grounding")
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
        original = copy.deepcopy(graph["resources"])
    assert client.get(f"/api/courses/{course_id}/materials").json()["materials"] == []
    assert client.get(f"/api/courses/{course_id}").json()["documents"][0]["postLessonCount"] == 0
    response = client.post(f"/api/documents/{upload['documentId']}/materials").json()
    assert response["status"] == "queued"
    assert work_once(factory, services)
    assert client.get(f"/api/courses/{course_id}/materials").json()["materials"]
    with factory() as db:
        packs = db.get(Document, upload["documentId"]).graph["resources"]
        for key, pack in packs.items():
            assert (
                pack["tests"] == original[key]["tests"]
                and pack["grounding"]["status"] == "supported"
            )


@pytest.mark.parametrize("workflow", ["tutoring", "assessment"])
def test_draft_source_change_during_model_call_keeps_pinned_release_evidence(
    stack, monkeypatch, workflow
):
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    if workflow == "assessment":
        activity = start(stack, course_id)["activity"]
    generate = services.generate

    def change_source(role, instruction, context, output):
        result = generate(role, instruction, context, output)
        if (workflow == "tutoring" and output is GroundingReview) or (
            workflow == "assessment" and output is Assessment
        ):
            with factory.begin() as db:
                db.scalar(
                    select(Chunk).where(Chunk.document_id == upload["documentId"])
                ).text = "The course source was replaced during generation."
        return result

    monkeypatch.setattr(services, "generate", change_source)
    if workflow == "tutoring":
        assert start(stack, course_id)["activity"] is not None
    else:
        response = client.post(
            f"/api/activities/{activity['id']}/responses",
            json={
                "operationId": "source-race",
                "expectedLearnerVersion": 0,
                "choiceId": "a",
            },
        ).json()
        assert work_once(factory, services)
        run = client.get(f"/api/agent-activity/runs/{response['runId']}").json()
        assert run["status"] == "waiting_for_learner"
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == (
        1 if workflow == "assessment" else 0
    )


def test_legacy_activity_with_resolvable_sources_can_be_reviewed_and_assessed(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    activity = start(stack, course_id)["activity"]
    with factory.begin() as db:
        saved = db.get(Activity, activity["id"])
        saved.private = {
            k: v for k, v in saved.private.items() if k not in ("question", "grounding")
        }
    response = client.post(
        f"/api/activities/{activity['id']}/responses",
        json={
            "operationId": "legacy-supported",
            "expectedLearnerVersion": 0,
            "choiceId": "a",
        },
    ).json()
    assert work_once(factory, services)
    assert client.get(f"/api/submissions/{response['submissionId']}").json()["status"] == "assessed"


def test_rejected_material_pack_is_corrected_and_reviewed_before_publication(stack, monkeypatch):
    client, factory, services, _ = stack
    original = services.generate
    material_reviews, feedback_seen = [], []

    def generate(role, instruction, context, output):
        if issubclass(output, PostMaterials) and "sourceReviewFeedback" in context:
            feedback_seen.append(context["sourceReviewFeedback"])
        result = original(role, instruction, context, output)
        if output is GroundingReview and "lesson" in context["item"]:
            material_reviews.append(context)
            if len(material_reviews) == 1:
                result.status = "unsupported"
                result.summary = "Remove an unsupported explanation detail."
        return result

    monkeypatch.setattr(services, "generate", generate)
    course_id, uploaded = prepare(stack)
    assert len(material_reviews) == 2 and len(feedback_seen) == 1
    assert "unsupported explanation" in feedback_seen[0]["review"]["summary"]
    materials = client.get(f"/api/courses/{course_id}/materials").json()["materials"]
    assert len(materials) == 1
    with factory() as db:
        doc = db.get(Document, uploaded["documentId"])
        assert all(
            pack["grounding"]["status"] == "supported" for pack in doc.graph["resources"].values()
        )
