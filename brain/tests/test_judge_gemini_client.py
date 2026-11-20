"""The Gemini judge must use an API version that accepts a system instruction (v1beta).

google-genai 3.x defaults to v1, which answers 400 "Developer instruction is not enabled for api
version v1", so every verdict silently became a fallback verdict. No network: genai is faked.
"""
import sys
import types
from dataclasses import replace

from brain.judge import GEMINI_API_VERSION, Judge, gemini_http_options


def test_gemini_client_uses_v1beta(cfg, monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    genai = types.ModuleType("google.genai")
    genai.Client = FakeClient
    google = types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)

    judge = Judge(replace(cfg, judge_provider="gemini", gemini_api_key="test-placeholder",
                          judge_timeout_seconds=8.0))
    assert judge.provider == "gemini"
    opts = seen["http_options"]
    assert opts["api_version"] == "v1beta" == GEMINI_API_VERSION
    assert opts["timeout"] == 8000                 # google-genai wants milliseconds
    assert opts["retry_options"] == {"attempts": 1}  # no automatic retry


def test_gemini_options_follow_the_timeout_setting():
    assert gemini_http_options(2.5)["timeout"] == 2500


def test_judge_timeout_setting(monkeypatch):
    from shared.config import load_settings
    monkeypatch.setenv("CS_JUDGE_TIMEOUT_SECONDS", "3")
    assert load_settings().judge_timeout_seconds == 3.0
    monkeypatch.delenv("CS_JUDGE_TIMEOUT_SECONDS")
    assert load_settings().judge_timeout_seconds == 8.0


def test_overloaded_gemini_falls_back_without_waiting(cfg, monkeypatch):
    """A 503 / timeout from Gemini gives a fallback verdict at once: one attempt, no retry loop."""
    from brain.tests.test_judge import ctx

    calls = []

    class Models:
        def generate_content(self, **_):
            calls.append(1)
            raise RuntimeError("503 UNAVAILABLE: the model is overloaded")

    class FakeClient:
        def __init__(self, **_):
            self.models = Models()

    genai = types.ModuleType("google.genai")
    genai.Client = FakeClient
    google = types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)

    judge = Judge(replace(cfg, judge_provider="gemini", gemini_api_key="test-placeholder"))
    v = judge.judge(ctx())
    assert v.source == "fallback" and "gemini unavailable" in v.reason
    assert len(calls) == 1
