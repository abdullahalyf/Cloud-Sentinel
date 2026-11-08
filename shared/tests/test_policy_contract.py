"""
The policy contract (CONTRACTS §11, added 8 Nov).

A policy file is only ever allowed to replace the running policy after it passes validation,
and the errors have to name the exact path so whoever edited the file knows what to fix.
"""
from __future__ import annotations

import pytest

from shared.contracts import ACTION_TYPES
from shared.config import load_settings


def test_policy_reload_is_an_action_type():
    """A reload is something DONE, so it belongs in the actions table like every other event."""
    assert "POLICY_RELOAD" in ACTION_TYPES


def test_the_policy_reload_settings_exist(monkeypatch):
    monkeypatch.delenv("CS_POLICY_RELOAD_ENABLED", raising=False)
    monkeypatch.delenv("CS_POLICY_RELOAD_INTERVAL_SECONDS", raising=False)
    cfg = load_settings()
    assert cfg.policy_reload_enabled is True
    assert cfg.policy_reload_interval_seconds == 1.0

    monkeypatch.setenv("CS_POLICY_RELOAD_ENABLED", "false")
    monkeypatch.setenv("CS_POLICY_RELOAD_INTERVAL_SECONDS", "2.5")
    cfg = load_settings()
    assert cfg.policy_reload_enabled is False
    assert cfg.policy_reload_interval_seconds == 2.5


@pytest.mark.parametrize("name", ["policy_reload_enabled", "policy_reload_interval_seconds"])
def test_the_new_settings_have_a_default(name):
    """A missing env var must not break Settings (the dataclass has no default for it)."""
    assert hasattr(load_settings(), name)


def test_the_mock_serves_the_policy_view():
    """The mock's /v1/policy has the shape the real API serves (CONTRACTS §6)."""
    from fastapi.testclient import TestClient

    from shared.mocks.mock_api import app as mock_app

    view = TestClient(mock_app).get("/v1/policy").json()
    assert set(view) == {"version", "loaded_at", "source", "defaults", "agents", "tools", "last_error"}
    assert view["defaults"]["budget_usd"] == 0.5
    assert view["defaults"]["on_trip"] == "pause"
    assert view["defaults"]["on_hard_limit"] == "kill"
    assert view["agents"]["delta"]["budget_usd"] == 0.2


def test_the_mock_has_the_policy_endpoints():
    """The mock exposes the same policy endpoints as the real API (CONTRACTS §6)."""
    from fastapi.testclient import TestClient

    from shared.mocks.mock_api import app as mock_app

    c = TestClient(mock_app)
    assert c.get("/v1/policy").status_code == 200
    assert c.post("/v1/policy/reload").status_code == 200
    assert c.post("/v1/policy/validate", json={"yaml": "defaults: {}"}).status_code == 200
