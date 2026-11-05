import json

import httpx
import pytest
from pydantic import SecretStr

from learnloop.core.config import get_settings
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import Assessment, CourseRelationships
from learnloop.services.clients import Services


def mock_client(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("shape", ["embedding", "embeddings"])
def test_embedding_accepts_singular_and_standard_array(monkeypatch, shape):
    vector = [0.01] * 1024
    mock_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={shape: vector if shape == "embedding" else [vector]}
        ),
    )
    assert len(Services(get_settings()).embed("Passage")) == 1024


@pytest.mark.parametrize("value", [[0.1], [0] * 1024, ["not-a-number"] * 1024, [True] * 1024])
def test_invalid_embedding_rejected_before_indexing(monkeypatch, value):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json={"embedding": value}))
    with pytest.raises(ServiceError, match="dimensions"):
        Services(get_settings()).embed("Passage")


def test_generation_uses_requested_model_strict_schema_and_rejects_truncation(
    monkeypatch,
):
    settings = get_settings().model_copy(update={"llm_api_key": SecretStr("test-key")})

    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-6-luna"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "untrusted data" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"feedback":"partial","uncertain":false}'},
                    }
                ]
            },
        )

    mock_client(monkeypatch, handler)
    with pytest.raises(ServiceError, match="schema"):
        Services(settings).generate("Assessing", "Assess safely.", {}, Assessment)


def test_qdrant_retrieval_requires_owner_course_and_published_documents(monkeypatch):
    seen = []

    def handler(request):
        if request.url.path.endswith("/api/embed"):
            return httpx.Response(200, json={"embedding": [0.01] * 1024})
        body = json.loads(request.content)
        seen.extend(body["filter"]["must"])
        assert body["with_payload"] is False
        return httpx.Response(200, json={"status": "ok", "result": {"points": [{"id": "chunk-1"}]}})

    mock_client(monkeypatch, handler)
    settings = get_settings().model_copy(
        update={
            "database_url": SecretStr("postgresql://unused"),
            "qdrant_url": "http://qdrant.test",
        }
    )
    services = Services(settings)
    assert services.search("query", "owner-a", "course-a", ["published-document"], 5) == ["chunk-1"]
    assert {item["key"] for item in seen} == {"owner_id", "course_id", "document_id"}
    assert services.search("query", "owner-a", "course-a", [], 5) == []


def test_course_relationship_output_has_sufficient_budget_and_truncation_can_retry(monkeypatch):
    settings = get_settings().model_copy(update={"llm_api_key": SecretStr("test-key")})

    def handler(request):
        assert json.loads(request.content)["max_tokens"] == 16000
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        )

    mock_client(monkeypatch, handler)
    with pytest.raises(ServiceError) as error:
        Services(settings).generate("Expert", "Review all relationships.", {}, CourseRelationships)
    assert error.value.retryable and error.value.code == "incomplete_model_output"
