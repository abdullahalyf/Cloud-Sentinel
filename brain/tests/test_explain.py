"""
The incident explanation, brain side (A13).

The acceptance is a **parity test** (the real API and the mock say the same thing) and
a **golden-text test** for the fallback. Both are here, plus the cases that make the
two easy to get wrong: an agent with nothing to report, an agent whose events are
out of order, and a window that excludes the interesting part.

The golden text is pinned on the *endpoint*, not on the shared builder: the builder's
own words are pinned in `shared/tests/test_explain_contract.py`. What is pinned here is
that the brain's own collector produces the story the builder then writes — the event
order, the counts, and the window are the brain's job, and those are what can drift.
"""
from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from brain import explain
from brain.api import create_app
from brain.judge import _lost_a_number
from shared.contracts import ActionRow, AgentRow, AlertRow, VerdictRow
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


def client(sim, cfg, judge="fallback"):
    return TestClient(create_app(sim.store, sim.policy, cfg, "fake", judge))


def state(sim, agent_id, state, budget_usd=0.5, spend_usd=0.0):
    """
    Put an agent in a known state.

    The state lives in the `agents` row and the engine rewrites it every tick from
    its own breaker — so a test cannot simply assert "beta is suspicious" and hope
    the detectors fired in time. Writing the row pins the state without touching
    anything else.
    """
    row = AgentRow(agent_id, agent_id, "fake", "fake-" + agent_id, state,
                   budget_usd, spend_usd, 0, sim.now, baseline="{}")
    sim.store.upsert_agent(row)


# ── the endpoint ────────────────────────────────────────────────────────────
def test_the_explain_endpoint_returns_the_report(sim, cfg):
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/alpha/explain").json()
    for field in ("agent_id", "state", "minutes", "summary", "polished_summary", "events",
                  "counts", "outcome", "cost"):
        assert field in body, f"the explain endpoint has no {field}"
    assert body["agent_id"] == "alpha"


def test_the_explain_endpoint_404s_for_an_unknown_agent(sim, cfg):
    assert client(sim, cfg).get("/v1/agents/nope/explain").status_code == 404


def test_the_explain_endpoint_tells_a_healthy_agent_so(sim, cfg):
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/alpha/explain").json()
    assert body["summary"]
    assert "alpha" in body["summary"]


def test_the_explain_endpoint_needs_no_key(sim, cfg):
    """The whole point of the deterministic summary: it works offline."""
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/alpha/explain").json()
    assert body["polished_summary"] is None
    assert body["summary"]


# ── the golden text ─────────────────────────────────────────────────────────
def test_the_golden_text_of_a_story(sim, cfg):
    """The exact words of the fallback explanation.

    A test that only checked "there is a summary" would let the text drift into
    something vague. Pinning the words is what keeps the explanation useful.
    """
    sim.store.insert_alert(AlertRow("beta", "warning", "loop_semantic", "semantic loop score 0.85"))
    sim.store.insert_verdict(VerdictRow("beta", "fallback", "PAUSE", 0.85, "semantic_loop",
                                         "Same intent repeated 14x with failing tool calls."))
    sim.store.insert_action(ActionRow("beta", "PAUSE", "fallback", "semantic loop on order 4471",
                                      2.52, 210000))
    sim.run(3)
    state(sim, "beta", "suspicious")
    body = client(sim, cfg).get("/v1/agents/beta/explain").json()
    assert body["summary"] == (
        "beta is SUSPICIOUS: the brain paused it. "
        "In this window there were 1 action, 1 alert, 1 verdict. "
        "It has spent $0.0000 of its $0.50 budget. "
        "That intervention saved about $2.52. "
        "The judge said: Same intent repeated 14x with failing tool calls.")


def test_the_golden_text_of_an_agent_with_nothing_to_report(sim, cfg):
    """An agent that never did anything gets a clear sentence, not an empty one."""
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/gamma/explain").json()
    assert body["summary"] == (
        "gamma is HEALTHY. Nothing happened in this window: no alert fired, no judge "
        "verdict was reached, and no action was taken.")
    assert body["events"] == []
    assert body["outcome"] is None


def test_the_golden_text_names_the_outcome(sim, cfg):
    sim.store.insert_action(ActionRow("beta", "KILL", "rules", "Hard limit: 80,816 tokens/min"))
    sim.run(3)
    state(sim, "beta", "killed")
    body = client(sim, cfg).get("/v1/agents/beta/explain").json()
    assert body["outcome"] == "KILL"
    assert "killed" in body["summary"]


# ── the story is in order ───────────────────────────────────────────────────
def test_the_events_are_in_time_order(sim, cfg):
    """An alert that came after a verdict cannot have caused it, so the order matters."""
    sim.store.insert_verdict(VerdictRow("beta", "fallback", "PAUSE", 0.9, "semantic_loop", "loop"))
    sim.store.insert_alert(AlertRow("beta", "warning", "loop_semantic", "flagged"))
    sim.store.insert_action(ActionRow("beta", "PAUSE", "fallback", "paused"))
    sim.run(3)
    events = client(sim, cfg).get("/v1/agents/beta/explain").json()["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.index("alert") < kinds.index("verdict") < kinds.index("action")
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)


def test_the_counts_match_the_events(sim, cfg):
    sim.store.insert_alert(AlertRow("beta", "warning", "loop_semantic", "flagged"))
    sim.store.insert_alert(AlertRow("beta", "critical", "token_spike", "spike"))
    sim.store.insert_verdict(VerdictRow("beta", "fallback", "PAUSE", 0.9, "semantic_loop", "loop"))
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/beta/explain").json()
    assert body["counts"]["alerts"] == 2
    assert body["counts"]["verdicts"] == 1
    assert body["counts"]["actions"] == 0


def test_only_this_agents_events_are_in_the_report(sim, cfg):
    """Another agent's alert must not show up in this agent's story."""
    sim.store.insert_alert(AlertRow("gamma", "warning", "token_spike", "gamma's problem"))
    sim.store.insert_alert(AlertRow("beta", "warning", "loop_semantic", "beta's problem"))
    sim.run(3)
    events = client(sim, cfg).get("/v1/agents/beta/explain").json()["events"]
    details = [e["detail"] for e in events]
    assert "beta's problem" in details
    assert "gamma's problem" not in details


# ── the window ──────────────────────────────────────────────────────────────
def test_the_window_excludes_the_old_events(sim, cfg):
    """`?minutes=` really is a window: an old alert is not part of "the last minute"."""
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sim.store.insert_alert(AlertRow("beta", "warning", "loop_semantic", "ancient"))
    sim.store._exec("update alerts set created_at=? where message='ancient'", (old,))
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/beta/explain?minutes=10").json()
    assert "ancient" not in [e["detail"] for e in body["events"]]


def test_a_longer_window_brings_the_old_events_back(sim, cfg):
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sim.store.insert_alert(AlertRow("beta", "warning", "loop_semantic", "ancient"))
    sim.store._exec("update alerts set created_at=? where message='ancient'", (old,))
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/beta/explain?minutes=180").json()
    assert "ancient" in [e["detail"] for e in body["events"]]


def test_the_window_is_clamped(sim, cfg):
    sim.run(3)
    body = client(sim, cfg).get("/v1/agents/alpha/explain?minutes=999999").json()
    assert body["minutes"] <= 24 * 60


# ── the parity with the mock ────────────────────────────────────────────────
def test_the_real_api_and_the_mock_say_the_same_thing(sim, cfg):
    """The parity test: the same agent, the same shape, the same summary."""
    sim.run(3)
    mock_api.seed()
    try:
        real = client(sim, cfg).get("/v1/agents/beta/explain")
        mock = TestClient(mock_app).get("/v1/agents/beta/explain")
    finally:
        mock_api.seed()
    assert real.status_code == 200, real.text
    assert mock.status_code == 200, mock.text
    real, mock = real.json(), mock.json()
    assert set(real) == set(mock)
    assert set(real["cost"]) == set(mock["cost"])
    assert set(real["counts"]) == set(mock["counts"])
    assert real["summary"].startswith("beta is")
    assert mock["summary"].startswith("beta is")


def test_the_mock_leads_the_real_api_until_the_brain_lands(sim, cfg):
    """Both sides have the endpoint now, so the gap row in CONTRACTS.md can go."""
    sim.run(3)
    real = client(sim, cfg).get("/v1/agents/beta/explain")
    assert real.status_code == 200


# ── the Claude polish ───────────────────────────────────────────────────────
def test_a_polish_that_drops_a_number_is_rejected():
    """A rewrite that loses "$0.2500" is worse than no rewrite: the operator would read
    a fluent sentence that says something subtly different from what happened."""
    assert _lost_a_number("spent $0.2500 of $0.50", "spent a little of its budget")
    assert not _lost_a_number("spent $0.2500 of $0.50", "spent $0.2500 of its $0.50 budget")
    assert not _lost_a_number("no numbers here", "still no numbers")


def test_the_polish_is_skipped_without_a_key(sim, cfg):
    from brain.explain import polish

    report = {"agent_id": "beta", "summary": "beta is paused: the brain paused it."}
    assert polish(dict(report), cfg=replace(cfg, judge_provider="fallback"))["polished_summary"] is None


def test_the_polish_never_breaks_the_endpoint(sim, cfg, monkeypatch):
    """A failing polish must not take the endpoint down: the deterministic summary is
    the answer, the polish is the extra."""
    from brain.explain import polish

    class Broken:
        provider = "claude"

        def polish_explanation(self, report):
            raise RuntimeError("the model is down")

    import brain.judge as judge_module

    monkeypatch.setattr(judge_module, "Judge", lambda cfg: Broken())
    out = polish({"agent_id": "beta", "summary": "beta is paused."}, cfg=cfg)
    assert out["polished_summary"] is None
    assert out["summary"] == "beta is paused."
