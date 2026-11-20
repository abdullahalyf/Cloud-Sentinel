"""The Gemini judge must use an API version that accepts a system instruction (v1beta).

google-genai 3.x defaults to v1, which answers 400 "Developer instruction is not enabled for api
version v1", so every verdict silently became a fallback verdict. No network: genai is faked.
"""
import sys
import types
from dataclasses import replace

from brain.judge import GEMINI_API_VERSION, Judge


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

    judge = Judge(replace(cfg, judge_provider="gemini", gemini_api_key="test-placeholder"))
    assert judge.provider == "gemini"
    assert seen["http_options"] == {"api_version": "v1beta"} == {"api_version": GEMINI_API_VERSION}
