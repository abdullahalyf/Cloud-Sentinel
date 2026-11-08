"""
The incident explanation (A13) — the contract side.

Two things are pinned here:

  1. **The shape.** The mock API and the real API must return the same fields, or a
     dashboard written against the mock breaks on the real thing.
  2. **The golden text.** The summary is deterministic, so the exact words can be pinned.
     A golden test that only checked "there is a summary" would let the text drift into
     something vague; pinning the words is what keeps the explanation *useful*.

The mock leads the real API here (the contract lands the mock first, the brain branch
follows), so these tests are about the shared builder and the mock's endpoint.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

from shared.contracts import explain_event, explain_report, explain_summary
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


def _client() -> TestClient:
    return TestClient(mock_app)


# ── the shared builder ──────────────────────────────────────────────────────
def test_a_report_with_no_events_says_nothing_happened():
    report = explain_report("alpha", "healthy", [])
    assert report["summary"] == ("alpha is HEALTHY. Nothing happened in this window: no alert fired, "
                                 "no judge verdict was reached, and no action was taken.")
    assert report["events"] == []
    assert report["outcome"] is None


def test_the_report_has_every_field_the_contract_names():
    report = explain_report("beta", "paused", [], minutes=10.0)
    for field in ("agent_id", "state", "minutes", "summary", "polished_summary", "events",
                  "counts", "outcome", "cost"):
        assert field in report, f"the report has no {field}"
    for field in ("spend_usd", "budget_usd", "saved_usd"):
        assert field in report["cost"], f"cost has no {field}"
    for field in ("alerts", "verdicts", "actions", "heals"):
        assert field in report["counts"], f"counts has no {field}"


def test_the_polished_summary_is_null_until_somebody_polishes_it():
    """The Claude polish is the brain's job. The builder must never be able to break the
    endpoint, so it starts as null and the client falls back to `summary`."""
    report = explain_report("beta", "paused", [explain_event("verdict", 1.0, "PAUSE", "loop")])
    assert report["polished_summary"] is None
    assert report["summary"]


def test_the_counts_match_the_events():
    events = [explain_event("alert", 1.0, "x"), explain_event("verdict", 2.0, "PAUSE", "y"),
              explain_event("action", 3.0, "PAUSE", "z")]
    report = explain_report("beta", "paused", events)
    assert report["counts"] == {"alerts": 1, "verdicts": 1, "actions": 1, "heals": 0}


def test_the_outcome_is_the_last_action():
    events = [explain_event("verdict", 1.0, "PAUSE", "loop"), explain_event("action", 2.0, "PAUSE", "x")]
    assert explain_report("beta", "paused", events)["outcome"] == "PAUSE"


def test_the_outcome_falls_back_to_the_verdict_when_nothing_was_done():
    events = [explain_event("verdict", 1.0, "WARN", "watching")]
    assert explain_report("beta", "suspicious", events)["outcome"] == "WARN"


def test_the_summary_is_the_golden_text():
    """The exact words. A test that only checked "there is some text" would let this
    drift into something vague."""
    events = [
        explain_event("alert", 10.0, "rules flagged it", "semantic loop score 0.85"),
        explain_event("verdict", 20.0, "PAUSE", "Same intent repeated 14x with failing tool calls."),
        explain_event("action", 30.0, "PAUSE", "semantic loop on order 4471"),
    ]
    assert explain_summary("beta", "paused", events, spend_usd=0.25, budget_usd=0.5, saved_usd=2.52) == (
        "beta is PAUSED: the brain paused it. "
        "In this window there were 1 action, 1 alert, 1 verdict. "
        "It has spent $0.2500 of its $0.50 budget. "
        "That intervention saved about $2.52. "
        "The judge said: Same intent repeated 14x with failing tool calls.")


def test_the_summary_does_not_mention_money_when_there_is_no_budget():
    events = [explain_event("action", 1.0, "KILL", "hard limit")]
    text = explain_summary("gamma", "killed", events)
    assert "budget" not in text
    assert "saved" not in text


def test_the_summary_says_the_agent_is_healthy_when_nothing_happened():
    assert "HEALTHY" in explain_summary("alpha", "healthy", [])


def test_the_summary_does_not_crash_on_an_empty_state():
    assert explain_summary("alpha", "", []) is not None


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_explain_endpoint():
    r = _client().get("/v1/agents/beta/explain")
    assert r.status_code == 200
    body = r.json()
    for field in ("agent_id", "state", "minutes", "summary", "polished_summary", "events",
                  "counts", "outcome", "cost"):
        assert field in body, f"the mock's explain has no {field}"


def test_the_mock_explain_has_the_same_shape_as_the_builder():
    body = _client().get("/v1/agents/beta/explain").json()
    expected = explain_report("beta", body["state"], body["events"], minutes=body["minutes"],
                               spend_usd=body["cost"]["spend_usd"], budget_usd=body["cost"]["budget_usd"],
                               saved_usd=body["cost"]["saved_usd"])
    assert set(body) == set(expected)


def test_the_mock_explain_404s_for_an_unknown_agent():
    assert _client().get("/v1/agents/nope/explain").status_code == 404


def test_the_mock_explain_tells_the_story_in_order():
    """The chain is the point: alert, then verdict, then action, then heal."""
    events = _client().get("/v1/agents/beta/explain").json()["events"]
    kinds = [e["kind"] for e in events]
    assert kinds == sorted(kinds, key=lambda k: ["alert", "verdict", "action", "heal"].index(k))
    assert "alert" in kinds and "verdict" in kinds and "action" in kinds


def test_the_mock_explain_keeps_the_minutes_it_was_asked_for():
    body = _client().get("/v1/agents/beta/explain?minutes=30").json()
    assert body["minutes"] == 30.0
