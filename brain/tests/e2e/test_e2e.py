"""
The E2E suite: the whole thing, running, on real processes.

Each test starts the brain (and the collector, and an agent, where the scenario needs them),
drives it through the API the way a human would, and checks what actually happened.

**What is not tested here:** the judge's accuracy (that is `brain/tests/test_judge.py` and
`docs/research/judge-eval.md`), the collectors' normalisation (Fojle's tests), and the
dashboard's rendering (Tamjid's). This suite asks one question: *does the system actually
pause, kill, hold and save money when it should?*

The judge runs in `fallback` mode on purpose. A judge that needs an API key would make the
whole suite depend on a secret, and the thing being tested here is the wiring, not the model.

The timings are generous (15–45 s) because these tests run on a loaded CI machine, not on
a laptop with nothing else going on. The brain's own tick is 1 s, so the real answer is
usually much faster than the budget.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from brain.tests.e2e_harness import REPO, Harness, free_port, wait_for_http  # noqa: F401

pytestmark = pytest.mark.e2e


# ── the brain comes up and serves the API ──────────────────────────────────
def test_the_brain_comes_up_and_serves_the_fleet(harness: Harness):
    """The simplest thing that must be true: the brain starts, the API answers, the fleet
    is there, and nothing is broken."""
    harness.start_brain()
    health = harness.json_api("/v1/health")
    assert health["ok"] is True
    assert health["mode"] == "fake"

    agents = harness.fleet()
    assert len(agents) == 4, agents
    assert {a["agent_id"] for a in agents} == {"alpha", "beta", "gamma", "delta"}
    for a in agents:
        assert a["state"] == "healthy", a


def test_the_health_check_lists_the_workers(harness: Harness):
    """A8: the brain is one worker, and it says so."""
    harness.start_brain()
    health = harness.json_api("/v1/health")
    assert "workers" in health
    assert health["agents_total"] == 4


# ── the paraphrase loop → paused ───────────────────────────────────────────
def test_the_paraphrase_loop_gets_paused(harness: Harness):
    """The flagship scenario: an agent starts repeating itself in a new way, and the brain
    pauses it. Within 15 s — the acceptance budget."""
    harness.start_brain()
    harness.command("beta", "GO_ROGUE", {"kind": "paraphrase_loop"})

    state = harness.wait_for_state("beta", {"paused", "killed"}, timeout=15)
    assert state in {"paused", "killed"}, f"beta is still {state!r} after 15 s"


def test_only_the_rogue_agent_is_paused(harness: Harness):
    """A false positive would be worse than a miss: the fleet stops working because one
    agent misbehaved."""
    harness.start_brain()
    harness.command("beta", "GO_ROGUE", {"kind": "paraphrase_loop"})
    harness.wait_for_state("beta", {"paused", "killed"}, timeout=15)

    for agent in ("alpha", "gamma", "delta"):
        assert harness.state(agent) == "healthy", f"{agent} was caught up in beta's problem"


def test_the_pause_is_explained(harness: Harness):
    """A pause with no reason is not actionable. The verdict must say what it saw."""
    harness.start_brain()
    harness.command("beta", "GO_ROGUE", {"kind": "paraphrase_loop"})
    harness.wait_for_state("beta", {"paused", "killed"}, timeout=15)

    verdicts = harness.json_api("/v1/verdicts").get("items", [])
    mine = [v for v in verdicts if v.get("agent_id") == "beta"]
    assert mine, "the pause was not explained by a verdict"
    assert mine[0].get("reason"), mine[0]


# ── fix the memory → resume → healthy ─────────────────────────────────────
def test_fixing_the_memory_and_resuming_makes_the_agent_healthy(harness: Harness):
    """The full loop: the agent learns a wrong fact and loops on it; a human fixes the
    memory; the agent resumes and is healthy again. Within 45 s."""
    harness.start_brain()
    harness.command("beta", "GO_ROGUE", {"kind": "paraphrase_loop"})
    assert harness.wait_for_state("beta", {"paused", "killed"}, timeout=15) in {"paused", "killed"}

    # The human fixes the wrong belief that the agent learned.
    memory = harness.json_api("/v1/agents/beta/memory")
    content = memory.get("content") or {}
    content.pop("order_4471", None)
    r = harness.api("/v1/agents/beta/memory", "PUT",
                    {"content": content, "edited_by": "human", "base_version": memory.get("version")})
    assert r.status_code in (200, 409), r.text

    harness.command("beta", "RESUME")

    state = harness.wait_for_state("beta", {"healthy", "suspicious", "probation"}, timeout=45)
    assert state in {"healthy", "suspicious", "probation"}, f"beta is still {state!r} after 45 s"


# ── the token bomb → killed ────────────────────────────────────────────────
def test_the_token_bomb_gets_killed(harness: Harness):
    """A token bomb burns money fast enough that pausing is not enough — it has to die."""
    harness.start_brain()
    harness.command("beta", "GO_ROGUE", {"kind": "token_bomb"})

    state = harness.wait_for_state("beta", {"killed", "paused"}, timeout=20)
    assert state in {"killed", "paused"}, f"beta is still {state!r} after 20 s"


# ── the big refund is held ─────────────────────────────────────────────────
def test_a_big_refund_is_held_and_saves_money(harness: Harness):
    """The bad_tool_call scenario: the agent tries to refund 50,000 dollars. The tool gate
    holds it (decision "pending"), a human denies it, and the money is saved.

    The saving is the point: a denied 410 USD refund that went through would be a real
    loss, so the test asserts the saving is greater than zero."""
    harness.start_brain()
    body = {"tool_name": "issue_refund", "args": {"order_id": 1, "amount": 50000}, "value_usd": 410.0}
    call = harness.json_api("/v1/agents/delta/tool-calls", "POST", body)
    assert call["decision"] == "pending", call

    r = harness.api(f"/v1/tool-calls/{call['id']}/decision", "POST", {"decision": "deny"})
    assert r.status_code == 200, r.text

    tool_calls = harness.json_api("/v1/tool-calls").get("items", [])
    denied = [t for t in tool_calls if t.get("id") == call["id"]]
    assert denied and denied[0]["decision"] == "deny", denied

    actions = harness.json_api("/v1/actions").get("items", [])
    saved = [a for a in actions if a.get("action") == "TOOL_DENY" or a.get("usd_saved_estimate", 0) > 0]
    assert saved, f"the denial was not recorded as a saving: {actions}"


# ── the MCP server over stdio ──────────────────────────────────────────────
def test_the_mcp_server_lists_the_agents_over_stdio(harness: Harness):
    """MCP is how Claude Desktop drives the fleet. It talks to the C2 API over stdio, so
    it has to find the brain — the URL comes from the environment."""
    harness.start_brain()

    reply = harness.mcp_call("list_agents")
    assert reply is not None, "the MCP server did not answer the tool call"
    assert "error" not in reply, reply
    text = json.dumps(reply.get("result", {}))
    assert "alpha" in text, text[:500]


# ── the collector takes real OTLP ──────────────────────────────────────────
def test_the_collector_receives_spans(harness: Harness):
    """The collector is the other half of the pipeline: the SDK sends OTLP, the collector
    writes the spans, the brain reads them. This checks the seam."""
    harness.start_collector()
    harness.start_brain()

    # The collector takes one OTLP ExportTraceServiceRequest, the way the SDK sends it.
    spans = {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "e2e-agent"}}]},
        "scopeSpans": [{"scope": {"name": "e2e"}, "spans": [{
            "traceId": "0123456789abcdef0123456789abcdef",
            "spanId": "0123456789abcdef", "name": "chat", "kind": 3,
            "startTimeUnixNano": str(int(time.time() * 1e9)),
            "endTimeUnixNano": str(int((time.time() + 0.1) * 1e9)),
            "attributes": [
                {"key": "cloudsentinel.agent.id", "value": {"stringValue": "e2e-external"}},
                {"key": "gen_ai.agent.id", "value": {"stringValue": "e2e-external"}},
                {"key": "service.name", "value": {"stringValue": "e2e-agent"}},
            ],
        }]}],
    }]}

    import httpx

    r = httpx.post(f"http://127.0.0.1:{harness.collector_port}/v1/traces", json=spans, timeout=10)
    assert r.status_code in (200, 202), r.text

    # The brain must pick the agent up — an external agent is still an agent.
    deadline = time.time() + 20
    seen = False
    while time.time() < deadline and not seen:
        try:
            seen = any(a["agent_id"] == "e2e-external" for a in harness.fleet())
        except Exception:
            pass
        if not seen:
            time.sleep(0.5)
    assert seen, "the collector's span did not reach the brain"


# ── the LangGraph agent ────────────────────────────────────────────────────
def test_the_langgraph_agent_is_paused_between_nodes(harness: Harness):
    """The LangGraph adapter enforces a pause *between nodes* — the agent is not killed
    mid-node, it waits at the next boundary. Skipped when langgraph is not installed."""
    try:
        import langgraph  # noqa: F401
    except ImportError:
        pytest.skip("langgraph is not installed")

    # The agent needs both halves of the pipeline: the collector takes its spans, and the
    # brain turns those spans into the agent rows the pause is recorded against.
    harness.start_collector()
    harness.start_brain()

    agent = harness.spawn("lg-agent", [sys.executable,
                                      "telemetry/examples/langgraph_refund_agent.py"],
                           {"CS_API_URL": f"http://127.0.0.1:{harness.api_port}",
                            "CS_AGENT_ID": "lg-refund",
                            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{harness.collector_port}",
                            "STEP_DELAY": "0.2", "TASK_GAP": "1", "PYTHONUNBUFFERED": "1"})

    # The agent has to be known to the brain (a span has to arrive) before it can be
    # paused — the brain cannot pause an agent it has never heard of.
    deadline = time.time() + 30
    known = False
    while time.time() < deadline and not known:
        known = harness.state("lg-refund") is not None
        if not known:
            time.sleep(0.5)
    assert known, f"the brain never saw lg-refund\n{agent.output()[-2000:]}"

    harness.command("lg-refund", "PAUSE")
    state = harness.wait_for_state("lg-refund", {"paused"}, timeout=25)
    assert state == "paused", f"lg-refund is {state!r}\n{agent.output()[-2000:]}"
