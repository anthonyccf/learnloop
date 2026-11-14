from tests.release_fixtures import seed_legacy_release

"""Isolated API checks for chat ownership, public context, and assistance policy."""

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from learnloop.api import create_app
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import grounding_fingerprint
from learnloop.core.schemas import PlanChoice, Question, TutorChatReply, TutorObservation
from learnloop.persistence.database import (
    Activity,
    Base,
    Chunk,
    Course,
    Document,
    LearnerState,
    StudySession,
)
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare


@pytest.fixture
def chat_stack():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = SimpleNamespace(
        api_token=SecretStr("test-token"), local_owner_id="owner", max_upload_bytes=100000
    )
    services = SimpleNamespace(context=None, fail=False, during_reply=None)

    def generate(role, instruction, context, output):
        assert role == "Tutoring" and output is TutorChatReply
        services.context = context
        if services.fail:
            raise ServiceError("unavailable", "Tutor temporarily unavailable.")
        if services.during_reply:
            services.during_reply()
        return TutorChatReply(text="Consider the object file stage before linking.")

    services.generate = generate
    with factory.begin() as db:
        db.add(Course(id="course", owner_id="owner", title="Systems"))
        db.add(
            Document(
                id="doc",
                course_id="course",
                filename="Systems.txt",
                sha256="test",
                content_type="text/plain",
                content=b"source",
                status="published",
                graph={
                    "concepts": [
                        {
                            "id": "compile",
                            "title": "Compilation",
                            "summary": "Compilation produces object code.",
                            "sources": [],
                        }
                    ],
                    "prerequisites": [],
                    "resources": {
                        "compile": {
                            "lesson": {
                                "title": "Compilation",
                                "explanation": "A compiler produces object code.",
                                "sources": [],
                            },
                            "tests": [{"correctChoiceId": "private-answer"}],
                        }
                    },
                },
            )
        )
        db.add(
            LearnerState(id="state", course_id="course", owner_id="owner", version=3, evidence={})
        )
        db.add(
            StudySession(
                id="session",
                course_id="course",
                owner_id="owner",
                status="active",
                current_activity_id="activity",
            )
        )
        db.add(
            Activity(
                id="activity",
                session_id="session",
                concept_id="compile",
                difficulty="intermediate",
                status="pending",
                hinted=False,
                public={
                    "prompt": "What is the next stage?",
                    "choices": [{"id": "a", "text": "Linking"}],
                    "sources": [],
                },
                private={
                    "correctChoiceId": "private-answer",
                    "explanation": "Private explanation.",
                },
            )
        )
        db.flush()
        text = "A compiler produces object code."
        db.add(
            Chunk(id="chunk", document_id="doc", course_id="course", ordinal=0, page=1, text=text)
        )
        doc = db.get(Document, "doc")
        graph = copy.deepcopy(doc.graph)
        source = {"chunkId": "chunk", "quote": text}
        graph["concepts"][0]["sources"] = [source]
        pack = graph["resources"]["compile"]
        pack["lesson"]["sources"] = [source]
        pack["tests"][0]["sources"] = [source]
        pack["grounding"] = {
            "fingerprint": grounding_fingerprint(
                {"lesson": pack["lesson"], "tests": pack["tests"]}, {"chunk": {"text": text}}
            ),
            "status": "supported",
        }
        doc.graph = graph
        seed_legacy_release(db, doc.course_id)
    with TestClient(create_app(settings, factory, services)) as client:
        client.headers["Authorization"] = "Bearer test-token"
        yield client, factory, services
    engine.dispose()


def post_chat(client, **overrides):
    return client.post(
        "/api/sessions/session/chat",
        json={
            "activityId": "activity",
            "message": "Please explain this idea.",
            "history": [],
            **overrides,
        },
    )


def test_chat_uses_public_context_and_marks_assistance_without_updating_evidence(chat_stack):
    client, factory, services = chat_stack
    response = post_chat(client)
    assert response.status_code == 200
    assert response.json()["assistanceUsed"] is True
    assert "private-answer" not in str(services.context)
    assert "Private explanation" not in str(services.context)
    assert services.context["lesson"]["explanation"] == "A compiler produces object code."
    with factory() as db:
        assert db.get(Activity, "activity").hinted is True
        assert db.get(LearnerState, "state").version == 3
        assert db.get(LearnerState, "state").evidence == {}


def test_review_chat_does_not_change_assistance(chat_stack):
    client, factory, _ = chat_stack
    with factory.begin() as db:
        db.get(Activity, "activity").status = "assessed"
    assert post_chat(client).json()["assistanceUsed"] is False
    with factory() as db:
        assert db.get(Activity, "activity").hinted is False


def test_chat_rejects_unauthorized_stale_and_submitted_requests(chat_stack):
    client, factory, _ = chat_stack
    assert (
        client.post(
            "/api/sessions/missing/chat", json={"activityId": "activity", "message": "Help"}
        ).status_code
        == 404
    )
    assert post_chat(client, activityId="old").status_code == 409
    with factory.begin() as db:
        db.get(StudySession, "session").owner_id = "someone-else"
    assert post_chat(client).status_code == 404
    with factory.begin() as db:
        db.get(StudySession, "session").owner_id = "owner"
        db.get(Activity, "activity").status = "submitted"
    assert post_chat(client).status_code == 409
    client.headers.pop("Authorization")
    assert post_chat(client).status_code == 401


def test_failed_reply_does_not_mark_assistance_and_stale_reply_is_not_delivered(chat_stack):
    client, factory, services = chat_stack
    services.fail = True
    assert post_chat(client).status_code == 503
    with factory() as db:
        assert db.get(Activity, "activity").hinted is False
    services.fail = False

    def submit_while_replying():
        with factory.begin() as db:
            db.get(Activity, "activity").status = "submitted"

    services.during_reply = submit_while_replying
    assert post_chat(client).status_code == 409
    with factory() as db:
        assert db.get(Activity, "activity").hinted is False


def test_chat_rejects_empty_messages_and_unbounded_history(chat_stack):
    client, _, _ = chat_stack
    assert post_chat(client, message="   ").status_code == 422
    assert post_chat(client, history=[{"role": "user", "text": "Hello"}] * 13).status_code == 422


@pytest.mark.parametrize("probe_passes", [True, False])
def test_tutor_remembers_a_gap_and_requests_private_practice(stack, monkeypatch, probe_passes):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    session_url = f"/api/sessions/{session['id']}"
    memory_url = f"/api/courses/{course_id}/learner-memory"
    assert work_once(factory, services)
    first = client.get(session_url).json()["activity"]
    generate = services.generate
    probe_requests = []
    summary = "Confuses the direction of a gradient update."

    def tutor_with_gap(role, instruction, context, output):
        if output is TutorChatReply:
            return TutorChatReply(
                text="Think about the direction that reduces the loss.",
                observation=TutorObservation(
                    kind="gap", summary=summary, quote="I confuse which way the step goes"
                ),
            )
        if output is PlanChoice:
            assert context["learnerMemory"][first["conceptId"]]["gap"]["summary"] == summary
        if output is Question and "diagnosticFocus" in context:
            assert role == "Expert" and context["diagnosticFocus"] == summary
            probe_requests.append(context["diagnosticFocus"])
            if not probe_passes:
                raise ServiceError("insufficient_evidence", "Cannot support the probe.", False)
        return generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", tutor_with_gap)
    for message in ["Please help", "I confuse which way the step goes", "I confuse which way the step goes"]:
        client.post(f"{session_url}/chat", json={"activityId": first["id"], "message": message}).raise_for_status()
    with factory() as db:
        assert len(db.get(Activity, first["id"]).private["tutorObservations"]) == 1
    snapshot = client.get(memory_url)
    assert 'filename="learner-memory.json"' in snapshot.headers["Content-Disposition"]
    memory = snapshot.json()["objectives"][first["conceptId"]]
    assert memory["gap"]["summary"] == summary and memory["status"] == "unassessed"
    assert "I confuse which way the step goes" not in snapshot.text

    client.post(
        f"/api/activities/{first['id']}/responses",
        json={"operationId": "assisted", "expectedLearnerVersion": 0, "choiceId": "a"},
    ).raise_for_status()
    assert work_once(factory, services)
    client.post(f"{session_url}/end").raise_for_status()
    followup_session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 1}
    ).json()
    assert work_once(factory, services)
    followup = client.get(f"/api/sessions/{followup_session['id']}").json()["activity"]
    assert followup and "memoryTarget" not in followup
    assert len(probe_requests) == (1 if probe_passes else 3)
    with factory() as db:
        saved = db.get(Activity, followup["id"])
        assert bool(saved.private["memoryTarget"]) is probe_passes
        assert saved.private["expertOnDemand"] is False
    if probe_passes:
        client.post(
            f"/api/activities/{followup['id']}/responses",
            json={"operationId": "probe-answer", "expectedLearnerVersion": 1, "choiceId": "a"},
        ).raise_for_status()
        assert work_once(factory, services)
        memory = client.get(memory_url).json()["objectives"][first["conceptId"]]
        assert memory["gap"] is None and memory["status"] == "developing"
