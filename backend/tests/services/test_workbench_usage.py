"""Provider usage is recorded only when the provider actually supplies it."""

import httpx
from pydantic import SecretStr

from learnloop.core.config import get_settings
from learnloop.core.schemas import Assessment
from learnloop.runtime.usage import MeteredServices, UsageRecorder, usage_summary
from learnloop.services.clients import Services


def test_provider_usage_and_unknown_cost(monkeypatch):
    settings = get_settings().model_copy(update={"llm_api_key": SecretStr("test-key")})
    responses = [
        {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0012},
        {"prompt_tokens": 9, "completion_tokens": 4},
    ]

    def handler(request):
        return httpx.Response(200, json={
            "usage": responses.pop(0),
            "choices": [{"finish_reason": "stop", "message": {"content": '{"feedback":"Looks good", "uncertain":false}'}}],
        })

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    recorder = UsageRecorder()
    services = MeteredServices(Services(settings), recorder)
    services.generate("Tutoring", "Respond.", {}, Assessment)
    assert usage_summary(recorder.calls()) == {"calls": 1, "inputTokens": 10, "outputTokens": 5, "costUsd": 0.0012}
    services.generate("Tutoring", "Respond.", {}, Assessment)
    assert usage_summary(recorder.calls()) == {"calls": 2, "inputTokens": 19, "outputTokens": 9, "costUsd": None}
    assert usage_summary(None)["costUsd"] is None
