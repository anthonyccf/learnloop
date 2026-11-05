from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from learnloop.core.schemas import GroundingReview
from learnloop.evaluation.artifacts import read
from learnloop.evaluation.provider import BudgetExhausted, Provider, usage


def settings():
    return SimpleNamespace(
        llm_model="pinned-test-model",
        llm_api_key=SecretStr("private-token"),
        llm_base_url="https://example.invalid",
        request_timeout_seconds=90,
    )


def client(monkeypatch, with_usage=True):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            assert json["seed"] == 72 and json["temperature"] == 0.2
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "model": "pinned-test-model",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "cost": 0.001}
                    if with_usage
                    else {},
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"status":"supported","summary":"Controlled source review."}'
                            },
                        }
                    ],
                },
            )

    monkeypatch.setattr(httpx, "Client", Client)


def test_usage_budgets_and_sanitized_logs(monkeypatch, tmp_path):
    client(monkeypatch)
    provider = Provider(settings(), tmp_path, max_calls=1, max_tokens=100000)
    provider.generate("Expert", "Check the source.", {"data": "hidden-secret"}, GroundingReview)
    ledger = read(tmp_path / "call-00001.json")
    assert (
        ledger["inputTokens"] == 100 and ledger["outputTokens"] == 30 and ledger["costUsd"] == 0.001
    )
    assert "private-token" not in str(ledger) and "hidden-secret" not in str(ledger)
    with pytest.raises(BudgetExhausted):
        provider.generate("Expert", "Check.", {}, GroundingReview)
    assert usage(provider.calls)["calls"] == 1


def test_missing_provider_usage_stops_instead_of_reporting_zero(monkeypatch, tmp_path):
    client(monkeypatch, False)
    provider = Provider(settings(), tmp_path, max_tokens=100000)
    with pytest.raises(BudgetExhausted):
        provider.generate("Expert", "Check.", {}, GroundingReview)
    ledger = usage(provider.calls)
    assert ledger["usageComplete"] is False and ledger["costUsd"] is None


def test_parallel_preparation_partitions_share_a_conservative_finite_parent_budget(
    monkeypatch, tmp_path
):
    client(monkeypatch)
    parent = Provider(settings(), tmp_path, max_calls=10, max_tokens=100000)
    parent.generate("Expert", "Check.", {}, GroundingReview)
    children = [parent.partition(f"child-{i}", 3) for i in range(3)]
    assert sum(c.max_calls for c in children) + len(parent.calls) <= parent.max_calls
    assert sum(c.max_tokens for c in children) + parent.tokens <= parent.max_tokens
    with pytest.raises(BudgetExhausted):
        parent.partition("extra", 3)
    with pytest.raises(BudgetExhausted):
        parent.generate("Expert", "Check.", {}, GroundingReview)
    for child in children:
        child.generate("Expert", "Check.", {}, GroundingReview)
        assert len(child.calls) == 1
