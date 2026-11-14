import importlib

import cloudsentinel as cs


def _init(monkeypatch, **env):
    for k in ("CS_API_URL", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    old = cs._s.api_url
    try:
        cs.init(agent_id="t-defaults")
        return cs._s.api_url
    finally:
        cs._s.api_url = old


def test_default_api_url_is_ipv4(monkeypatch):
    assert _init(monkeypatch) == "http://127.0.0.1:8000"


def test_env_var_still_overrides_the_api_url(monkeypatch):
    assert _init(monkeypatch, CS_API_URL="http://brain:8000/") == "http://brain:8000"


def test_no_default_mentions_localhost():
    src = importlib.import_module("cloudsentinel").__file__
    text = open(src, encoding="utf-8").read()
    assert "http://localhost" not in text
