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
from learnloop.core.schemas import TutorChatReply
from learnloop.persistence.database import (
    Activity,
    Base,
    Chunk,
    Course,
    Document,
    LearnerState,
    StudySession,
)


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
