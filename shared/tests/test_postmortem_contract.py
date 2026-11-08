"""
The contract test for B2's incident postmortem.

An incident *is* an alert: the moment the brain flagged an agent. Everything that
followed — the verdict, the action, the heal — is part of that incident.

The report shape and the markdown rendering live in `shared/contracts.py`, because the
mock API and the real API must say the same thing. This test pins both.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.contracts import (postmortem_event, postmortem_markdown, postmortem_report,
                              postmortem_root_cause)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


# ── the shape ───────────────────────────────────────────────────────────────
def test_the_report_has_the_shape_the_task_names():
    report = postmortem_report(
        7, "beta",
        postmortem_root_cause("loop_semantic", "semantic_loop", "the belief kept it looping"),
        [postmortem_event("alert", 100.0, "loop_semantic", "flagged", "a1")],
        [{"span_id": "b" * 16, "trace_id": "a" * 32, "operation": "chat", "start_ts": 90.0}],
        {"usd_saved": 0.12, "tokens_saved": 1000, "spend_usd": 0.03},
        {"time_to_detect_seconds": 10.0, "time_to_heal_seconds": 5.0},
        "paused",
    )
    assert sorted(report) == ["agent_id", "evidence", "incident_id", "money", "resolution",
                              "root_cause", "timeline", "timings"]
    assert report["incident_id"] == 7
    assert report["agent_id"] == "beta"


def test_the_timeline_is_ordered_by_time():
    """The order is the point: an alert cannot precede the verdict that caused it."""
    report = postmortem_report(
        1, "beta", postmortem_root_cause("loop_semantic", "semantic_loop", "because"),
        [postmortem_event("action", 300.0, "PAUSE"),
         postmortem_event("evidence", 100.0, "it started looping"),
         postmortem_event("alert", 200.0, "loop_semantic")],
        [], {}, {})
    assert [e["ts"] for e in report["timeline"]] == [100.0, 200.0, 300.0]
    assert [e["kind"] for e in report["timeline"]] == ["evidence", "alert", "action"]


def test_the_root_cause_names_the_rule_and_the_pattern():
    root = postmortem_root_cause("loop_semantic", "semantic_loop", "the belief kept it looping")
    assert root["rule"] == "loop_semantic"
    assert root["pattern"] == "semantic_loop"
    assert root["headline"] == "loop_semantic — semantic_loop"


def test_the_root_cause_is_never_unknown_when_a_rule_fired():
    """A rule that fired is a root cause, even when the judge said nothing."""
    root = postmortem_root_cause("tool_cycle", "", "")
    assert root["rule"] == "tool_cycle"
    assert root["pattern"] != "unknown"
    assert root["headline"] == "tool_cycle"


def test_the_root_cause_says_unknown_when_nothing_is_known():
    root = postmortem_root_cause("", "", "")
    assert root["rule"] == "unknown"
    assert root["pattern"] == "unknown"
    assert root["headline"] == "unknown"


def test_a_timing_that_cannot_be_measured_is_none_not_zero():
    """"0.0" and "we do not know" are different facts, and only one of them is true."""
    report = postmortem_report(1, "beta", postmortem_root_cause("r", "p", "x"), [], [], {}, {})
    assert report["timings"]["time_to_detect_seconds"] is None
    assert report["timings"]["time_to_heal_seconds"] is None


def test_the_money_is_zero_when_nothing_was_saved():
    report = postmortem_report(1, "beta", postmortem_root_cause("r", "p", "x"), [], [], {}, {})
    assert report["money"]["usd_saved"] == 0.0
    assert report["money"]["tokens_saved"] == 0


def test_the_money_carries_the_roi_formula():
    report = postmortem_report(1, "beta", postmortem_root_cause("r", "p", "x"), [], [], {}, {})
    assert "KILL/PAUSE" in report["money"]["formula"]


def test_the_evidence_keeps_the_real_span_ids():
    evidence = [{"span_id": "abc123", "trace_id": "def456", "operation": "chat", "start_ts": 1.0}]
    report = postmortem_report(1, "beta", postmortem_root_cause("r", "p", "x"), [], evidence, {}, {})
    assert report["evidence"][0]["span_id"] == "abc123"
    assert report["evidence"][0]["trace_id"] == "def456"


# ── the markdown ────────────────────────────────────────────────────────────
def test_the_markdown_shows_the_same_numbers_as_the_json():
    report = postmortem_report(
        7, "beta", postmortem_root_cause("loop_semantic", "semantic_loop", "the belief kept it looping"),
        [postmortem_event("alert", 100.0, "loop_semantic", "flagged", "a1")],
        [{"span_id": "b" * 16, "trace_id": "a" * 32, "operation": "chat", "start_ts": 90.0}],
        {"usd_saved": 0.1234, "tokens_saved": 4321, "spend_usd": 0.05},
        {"time_to_detect_seconds": 12.5, "time_to_heal_seconds": 3.25},
        "paused",
    )
    md = postmortem_markdown(report)
    assert "$0.1234" in md
    assert "4,321 tokens" in md
    assert "12.5s" in md
    assert "3.2s" in md or "3.25s" in md
    assert "loop_semantic" in md
    assert "b" * 16 in md


def test_the_markdown_says_not_measured_for_an_unknown_timing():
    report = postmortem_report(1, "beta", postmortem_root_cause("r", "p", "x"), [], [], {}, {})
    md = postmortem_markdown(report)
    assert "not measured" in md


def test_the_markdown_of_an_empty_report_is_still_markdown():
    md = postmortem_markdown({})
    assert md.startswith("#")
    assert "No incident" in md


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_postmortem_of_an_incident():
    c = TestClient(mock_app)
    r = c.get("/v1/incidents/1/postmortem")
    assert r.status_code == 200
    body = r.json()
    assert body["incident_id"] == 1
    assert body["agent_id"] == "beta"
    assert body["timeline"]
    assert body["root_cause"]["rule"]
    assert body["root_cause"]["pattern"] != "unknown"


def test_the_mock_serves_the_postmortem_as_markdown():
    c = TestClient(mock_app)
    r = c.get("/v1/incidents/1/postmortem.md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    assert r.text.startswith("# Incident 1")


def test_the_mock_says_404_for_an_unknown_incident():
    c = TestClient(mock_app)
    assert c.get("/v1/incidents/9999/postmortem").status_code == 404
    assert c.get("/v1/incidents/9999/postmortem.md").status_code == 404


def test_the_mock_postmortem_says_the_same_thing_as_its_json():
    """The markdown endpoint must render the JSON endpoint's numbers, not its own."""
    c = TestClient(mock_app)
    body = c.get("/v1/incidents/1/postmortem").json()
    md = c.get("/v1/incidents/1/postmortem.md").text
    assert f"${body['money']['usd_saved']:.4f}" in md
