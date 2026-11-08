"""Every MCP tool (CONTRACTS §7) works against the mock API and the real API."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from brain import mcp_server as m
from brain.api import create_app
from shared.mocks import mock_api

WRITE_TOOLS = {"pause_agent", "resume_agent", "kill_agent", "set_budget", "edit_memory", "decide_tool_call",
               "decide_heal"}


def _route_to(monkeypatch, app):
    monkeypatch.setattr(m.httpx, "Client", lambda **kw: TestClient(app, headers=kw.get("headers")))


def test_sixteen_tools_with_contract_annotations():
    """CONTRACTS §7 — 16 tools after A5 added get_policy and validate_policy."""
    tools = {t.name: t for t in asyncio.run(m.mcp.list_tools())}
    assert len(tools) == 16
    for name, tool in tools.items():
        assert tool.annotations.destructive_hint == (name in WRITE_TOOLS), name
        assert tool.annotations.read_only_hint == (name not in WRITE_TOOLS), name


@pytest.fixture(params=["mock", "real"])
def api(request, monkeypatch, sim, cfg):
    mock_api.seed()
    if request.param == "mock":
        _route_to(monkeypatch, mock_api.app)
    else:
        sim.fleet.go_rogue("delta", "bad_tool_call", sim.now)
        sim.run(25)
        _route_to(monkeypatch, create_app(sim.store, sim.policy, cfg, "fake", "fallback"))
    yield request.param
    mock_api.seed()


def test_every_tool_round_trips(api):
    agents = m.list_agents()
    assert {a["agent_id"] for a in agents} >= {"alpha", "beta", "delta"}
    assert m.get_agent("beta")["agent"]["agent_id"] == "beta"
    assert "beta" in m.explain_agent("beta")
    for fn in (m.pause_agent, m.resume_agent, m.kill_agent):
        assert fn("alpha", "test")["status"] == "pending"
    assert m.set_budget("alpha", 2.0, "test")["status"] == "pending"
    mem = m.edit_memory("beta", {"order_4471": "cancelled - skip it"}, "test")
    assert mem["edited_by"] == "mcp" and m.get_memory("beta")["content"]["order_4471"].startswith("cancelled")
    pending = m.list_pending_tool_calls()
    assert pending, f"{api}: expected a held refund"
    done = m.decide_tool_call(pending[0]["id"], "deny", "test")
    assert done["decision"] == "deny" and done["decided_by"] == "mcp"
    assert "saved_usd" in m.get_roi_report()


def test_the_policy_tools_work(api):
    """A5: get_policy reads the policy in force, validate_policy checks a file's text."""
    policy = m.get_policy()
    assert policy["defaults"]["budget_usd"] == 0.5
    assert policy["last_error"] == ""
    ok = m.validate_policy("defaults:\n  budget_usd: 0.5\ntools:\n  - { match: '*', action: allow }\n")
    assert ok["ok"] is True and ok["errors"] == []
    bad = m.validate_policy("tools:\n  - { match: '*', action: block }\n")
    assert bad["ok"] is False
    assert "tools[0].action: must be one of allow, deny, approval" in bad["errors"]


def test_api_errors_become_readable_tool_errors(api):
    """A bad argument is caught locally (A7) — the message says what is wrong, not a 400."""
    with pytest.raises(m.ToolError, match="budget_usd must be between"):
        m.set_budget("alpha", -1, "bad")


def test_an_api_error_still_becomes_a_readable_error(api):
    """An error from the API itself (the agent does not exist) is still readable."""
    with pytest.raises(m.ToolError, match="not found"):
        m.get_agent("no-such-agent")
