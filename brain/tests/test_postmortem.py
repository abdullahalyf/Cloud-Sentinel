"""
The incident postmortem, brain side (B2).

An incident *is* an alert. The acceptance tests here are the ones that make
the postmortem easy to get wrong:

- the timeline is in the right order (an alert cannot precede the verdict that
  caused it, and a verdict from *before* the alert is somebody else's story);
- the root cause names the rule and the pattern, never "unknown";
- the evidence spans are *real* span ids from the store, not made up;
- the money saved uses the ROI formula and is 0 when nothing was saved;
- the time to detect is measured from the first evidence to the alert;
- the time to heal is measured from the alert to the action;
- the markdown renders the same numbers as the JSON;
- an unknown incident is a 404;
- the mock and the real API say the same thing (the parity test).

The report *shape* and the markdown renderer are pinned in
`shared/tests/test_postmortem_contract.py` — what is pinned here is that the
brain's own store produces the story the builder then writes.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from brain import postmortem
from brain.api import create_app
from shared.contracts import (ActionRow, AgentRow, AlertRow, SpanRow, VerdictRow,
                              postmortem_markdown)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


def client(sim, cfg, judge="fallback"):
    return TestClient(create_app(sim.store, sim.policy, cfg, "fake", judge))


def _agent(sim, agent_id="beta"):
    sim.store.upsert_agent(AgentRow(agent_id, agent_id, "fake", "fake-" + agent_id,
                                     "healthy", 1.0, 0.25, 100, sim.now, baseline="{}"))


def _span(sim, agent_id, span_id, trace_id, start_ts, operation="chat"):
    sim.store.insert_spans([SpanRow(agent_id=agent_id, operation=operation, name=operation,
                                    trace_id=trace_id, span_id=span_id, start_ts=start_ts,
                                    end_ts=start_ts + 1.0, duration_ms=1000.0)])


def _incident(sim, agent_id="beta", rule="loop_semantic", at=1000.0,
              message="the agent kept repeating itself"):
    """A full incident: evidence → alert → verdict → action.

    The rows are written with explicit timestamps, because the *gaps* between
    them are the numbers the postmortem reports.
    """
    _agent(sim, agent_id)
    _span(sim, agent_id, "b" * 16, "a" * 32, at - 12.0)
    sim.store.insert_alert(AlertRow(agent_id=agent_id, severity="critical", rule=rule,
                                    message=message, created_at=_iso(at)))
    sim.store.insert_verdict(VerdictRow(agent_id=agent_id, source="fallback", action="PAUSE",
                                         confidence=0.9, pattern="semantic_loop",
                                         reason="the belief kept it looping",
                                         created_at=_iso(at + 5.0)))
    sim.store.insert_action(ActionRow(agent_id=agent_id, action="PAUSE", actor="rules",
                                      reason="the loop did not stop",
                                      usd_saved_estimate=0.25, tokens_saved_estimate=4000,
                                      created_at=_iso(at + 9.0)))
    return at


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _alert_id(sim, agent_id="beta"):
    for row in sim.store.recent_alerts(limit=50):
        if row["agent_id"] == agent_id:
            return int(row["id"])
    raise AssertionError("no alert was written")


# ── the endpoint ────────────────────────────────────────────────────────────
def test_the_postmortem_endpoint_returns_the_report(sim, cfg):
    _incident(sim)
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    for field in ("incident_id", "agent_id", "root_cause", "timeline", "evidence",
                  "money", "timings", "resolution"):
        assert field in body, f"the postmortem has no {field}"


def test_the_postmortem_endpoint_404s_for_an_unknown_incident(sim, cfg):
    _incident(sim)
    assert client(sim, cfg).get("/v1/incidents/9999/postmortem").status_code == 404


def test_the_postmortem_endpoint_serves_markdown(sim, cfg):
    _incident(sim)
    r = client(sim, cfg).get("/v1/incidents/1/postmortem.md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    assert r.text.startswith("# Incident 1")


def test_the_postmortem_endpoint_404s_for_an_unknown_incident_in_markdown(sim, cfg):
    _incident(sim)
    assert client(sim, cfg).get("/v1/incidents/9999/postmortem.md").status_code == 404


# ── the timeline ────────────────────────────────────────────────────────────
def test_the_timeline_is_ordered_by_time(sim, cfg):
    """The order is the point: an alert cannot precede the verdict that caused it."""
    _incident(sim)
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    ts = [e["ts"] for e in body["timeline"]]
    assert ts == sorted(ts)
    kinds = [e["kind"] for e in body["timeline"]]
    assert kinds.index("evidence") < kinds.index("alert")
    assert kinds.index("alert") < kinds.index("verdict")
    assert kinds.index("verdict") < kinds.index("action")


def test_a_verdict_from_before_the_alert_is_not_this_incident(sim, cfg):
    """The brain flags first and the judge decides after — the other way round
    is somebody else's story."""
    _agent(sim)
    sim.store.insert_verdict(VerdictRow(agent_id="beta", source="fallback", action="WARN",
                                         confidence=0.5, pattern="old_news",
                                         reason="from last week", created_at=_iso(500.0)))
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="loop_semantic",
                                    message="now", created_at=_iso(1000.0)))
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    assert "old_news" not in postmortem_markdown(body)


def test_the_timeline_entries_carry_the_row_they_came_from(sim, cfg):
    """A timeline whose entries cannot be traced back to a row is a story."""
    _incident(sim)
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    for event in body["timeline"]:
        assert event["ref"], f"the {event['kind']} event has no ref"


# ── the root cause ──────────────────────────────────────────────────────────
def test_the_root_cause_names_the_rule_and_the_pattern(sim, cfg):
    _incident(sim)
    root = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["root_cause"]
    assert root["rule"] == "loop_semantic"
    assert root["pattern"] == "semantic_loop"
    assert root["pattern"] != "unknown"
    assert "loop_semantic" in root["headline"]


def test_the_root_cause_is_not_unknown_when_the_judge_said_nothing(sim, cfg):
    """A rule that fired is a root cause, even when the judge said nothing."""
    _agent(sim)
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="tool_cycle",
                                    message="the tools went round and round",
                                    created_at=_iso(1000.0)))
    root = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["root_cause"]
    assert root["rule"] == "tool_cycle"
    assert root["pattern"] != "unknown"


# ── the evidence ────────────────────────────────────────────────────────────
def test_the_evidence_spans_are_the_real_span_ids(sim, cfg):
    _incident(sim)
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    assert body["evidence"]
    assert body["evidence"][0]["span_id"] == "b" * 16
    assert body["evidence"][0]["trace_id"] == "a" * 32


def test_the_evidence_is_the_spans_from_before_the_alert(sim, cfg):
    """A span after the alert cannot have caused it."""
    _incident(sim)
    _span(sim, "beta", "c" * 16, "z" * 32, 1005.0)
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    assert "c" * 16 not in [s["span_id"] for s in body["evidence"]]


def test_an_incident_with_no_spans_has_no_evidence(sim, cfg):
    """No evidence is `[]`, not a made-up span."""
    _agent(sim)
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="loop_semantic",
                                    message="no spans today", created_at=_iso(1000.0)))
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    assert body["evidence"] == []


# ── the money ───────────────────────────────────────────────────────────────
def test_the_money_saved_is_the_sum_of_the_saving_actions(sim, cfg):
    _incident(sim)
    money = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["money"]
    assert money["usd_saved"] == 0.25
    assert money["tokens_saved"] == 4000


def test_the_money_carries_the_roi_formula(sim, cfg):
    _incident(sim)
    money = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["money"]
    assert "KILL/PAUSE" in money["formula"]


def test_an_action_that_saves_nothing_is_not_counted(sim, cfg):
    """A WARN stops no spending, so it saves no money."""
    _agent(sim)
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="loop_semantic",
                                    message="flagged", created_at=_iso(1000.0)))
    sim.store.insert_action(ActionRow(agent_id="beta", action="WARN", actor="rules",
                                      reason="just a warning", usd_saved_estimate=0.0,
                                      tokens_saved_estimate=0, created_at=_iso(1001.0)))
    money = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["money"]
    assert money["usd_saved"] == 0.0
    assert money["tokens_saved"] == 0


def test_an_incident_with_no_action_saved_nothing(sim, cfg):
    _agent(sim)
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="loop_semantic",
                                    message="flagged", created_at=_iso(1000.0)))
    money = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["money"]
    assert money["usd_saved"] == 0.0
    assert money["tokens_saved"] == 0


# ── the timings ─────────────────────────────────────────────────────────────
def test_the_time_to_detect_is_measured_from_the_first_evidence_to_the_alert(sim, cfg):
    _incident(sim)
    timings = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["timings"]
    assert timings["time_to_detect_seconds"] == 12.0


def test_the_time_to_heal_is_measured_from_the_alert_to_the_action(sim, cfg):
    _incident(sim)
    timings = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["timings"]
    assert timings["time_to_heal_seconds"] == 9.0


def test_a_timing_that_cannot_be_measured_is_none_not_zero(sim, cfg):
    """"0.0" and "we do not know" are different facts, and only one of them is true."""
    _agent(sim)
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="loop_semantic",
                                    message="no evidence, no action", created_at=_iso(1000.0)))
    timings = client(sim, cfg).get("/v1/incidents/1/postmortem").json()["timings"]
    assert timings["time_to_detect_seconds"] is None
    assert timings["time_to_heal_seconds"] is None


def test_the_markdown_says_not_measured_for_an_unknown_timing(sim, cfg):
    _agent(sim)
    sim.store.insert_alert(AlertRow(agent_id="beta", severity="warning", rule="loop_semantic",
                                    message="no evidence, no action", created_at=_iso(1000.0)))
    md = client(sim, cfg).get("/v1/incidents/1/postmortem.md").text
    assert "not measured" in md


# ── the markdown ────────────────────────────────────────────────────────────
def test_the_markdown_shows_the_same_numbers_as_the_json(sim, cfg):
    """A markdown that says "$0.25 saved" when the JSON says 0.25 is a report
    nobody can trust."""
    _incident(sim)
    c = client(sim, cfg)
    body = c.get("/v1/incidents/1/postmortem").json()
    md = c.get("/v1/incidents/1/postmortem.md").text
    assert f"${body['money']['usd_saved']:.4f}" in md
    assert f"{body['money']['tokens_saved']:,} tokens" in md
    assert "12.0s" in md
    assert "9.0s" in md
    assert "loop_semantic" in md
    assert "b" * 16 in md


# ── the parity with the mock ────────────────────────────────────────────────
def test_the_mock_and_the_real_api_say_the_same_thing(sim, cfg):
    """The mock leads the real API while the gap is open; the *shape* must match
    so a client written against the mock keeps working against the real thing."""
    mock_api.seed()
    try:
        _incident(sim)
        real = client(sim, cfg)
        mock = TestClient(mock_app)
        r = real.get(f"/v1/incidents/{_alert_id(sim)}/postmortem")
        m = mock.get("/v1/incidents/1/postmortem")
        assert r.status_code == 200 and m.status_code == 200
        assert set(r.json()) == set(m.json())
        assert set(r.json()["root_cause"]) == set(m.json()["root_cause"])
        assert set(r.json()["money"]) == set(m.json()["money"])
        assert set(r.json()["timings"]) == set(m.json()["timings"])
        assert set(r.json()["timeline"][0]) == set(m.json()["timeline"][0])
        assert set(r.json()["evidence"][0]) == set(m.json()["evidence"][0])
    finally:
        mock_api.seed()


def test_the_mock_and_the_real_api_404_on_the_same_unknown_incident(sim, cfg):
    mock_api.seed()
    try:
        assert client(sim, cfg).get("/v1/incidents/9999/postmortem").status_code == 404
        assert TestClient(mock_app).get("/v1/incidents/9999/postmortem").status_code == 404
    finally:
        mock_api.seed()


# ── the builder, on its own ─────────────────────────────────────────────────
def test_the_builder_returns_none_for_an_unknown_incident(sim, cfg):
    assert postmortem.build_postmortem(sim.store, 4242) is None


def test_the_resolution_says_what_happened(sim, cfg):
    _incident(sim)
    body = client(sim, cfg).get("/v1/incidents/1/postmortem").json()
    assert "PAUSE" in body["resolution"]
