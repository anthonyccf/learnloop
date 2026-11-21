"""Capture provider-reported usage without recording prompts or learner text."""

import copy
from threading import Lock


class UsageRecorder:
    def __init__(self, on_record=None):
        self._calls = []
        self._lock = Lock()
        self._on_record = on_record

    def record(self, usage):
        entry = usage if isinstance(usage, dict) else {}
        entry = {key: entry.get(key) for key in ("inputTokens", "outputTokens", "costUsd")}
        with self._lock:
            self._calls.append(entry)
            if self._on_record:
                self._on_record(entry)

    def calls(self):
        with self._lock:
            return copy.deepcopy(self._calls)


class MeteredServices:
    def __init__(self, services, recorder):
        self._services, self._recorder = services, recorder

    def __getattr__(self, name):
        return getattr(self._services, name)

    def generate(self, *args, **kwargs):
        try:
            return self._services.generate(*args, **kwargs)
        finally:
            self._recorder.record(getattr(self._services, "last_generation_usage", None))

    def verify(self, *args, **kwargs):
        verifier = getattr(self._services, "verify", None)
        if verifier is None:
            return self.generate("Expert", *args, **kwargs)
        try:
            return verifier(*args, **kwargs)
        finally:
            self._recorder.record(getattr(self._services, "last_generation_usage", None))


def usage_summary(calls):
    if calls is None:
        return {"calls": None, "inputTokens": None, "outputTokens": None, "costUsd": None}
    result = {"calls": len(calls)}
    for key in ("inputTokens", "outputTokens", "costUsd"):
        result[key] = sum(call[key] for call in calls) if all(call.get(key) is not None for call in calls) else None
    return result
