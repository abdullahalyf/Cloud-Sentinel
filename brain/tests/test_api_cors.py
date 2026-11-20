"""CORS for a dashboard on another domain (CS_CORS_ORIGINS). Off by default."""
from dataclasses import replace

from fastapi.testclient import TestClient

from brain.api import create_app
from shared.config import _csv


ORIGIN = "https://cloudsentinel.vercel.app"


def _client(sim, cfg):
    return TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback"))


def test_no_cors_headers_by_default(sim, cfg):
    r = _client(sim, replace(cfg, cors_origins=())).get("/v1/health", headers={"Origin": ORIGIN})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_listed_origin_gets_cors_headers(sim, cfg):
    c = _client(sim, replace(cfg, cors_origins=(ORIGIN,)))
    r = c.get("/v1/health", headers={"Origin": ORIGIN})
    assert r.headers["access-control-allow-origin"] == ORIGIN
    pre = c.options("/v1/fleet", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET",
                                          "Access-Control-Request-Headers": "X-CS-Token"})
    assert pre.status_code == 200


def test_other_origin_is_not_allowed(sim, cfg):
    r = _client(sim, replace(cfg, cors_origins=(ORIGIN,))).get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_csv_setting_parses_and_trims(monkeypatch):
    monkeypatch.setenv("CS_CORS_ORIGINS", " https://a.app/ , ,https://b.app ")
    assert _csv("CS_CORS_ORIGINS") == ("https://a.app", "https://b.app")
    monkeypatch.delenv("CS_CORS_ORIGINS")
    assert _csv("CS_CORS_ORIGINS") == ()
