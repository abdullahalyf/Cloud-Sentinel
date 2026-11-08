"""
A5: policy-as-code with hot reload. Acceptance tests.

The point of hot reload: an operator edits `policies.yaml` and the brain picks the change up
**while it runs** — no restart, no dropped requests. And if the file is broken, the last good
policy keeps working, because a typo in a YAML file must never take the guard down.

These tests check that:
  - a good file is swapped in and changes a tool-gate decision within 2 ticks
  - a broken file is rejected, the old policy stays in force, and a critical alert is raised
  - the validation errors name the exact path of the thing that is wrong
  - the API serves the policy, reloads it and validates YAML text
  - the MCP server exposes get_policy and validate_policy
  - the mock API has the same shapes
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from brain.policy import Policy, version_of
from brain.policy_reload import PolicyManager, summarize
from brain.policy_schema import validate, validate_yaml

# ── helpers ───────────────────────────────────────────────────────────────────

GOOD = """
defaults:
  budget_usd: 0.50
  on_trip: pause
  on_hard_limit: kill
agents:
  delta: { budget_usd: 0.20 }
tools:
  - { match: "delete_*",   action: deny,     reason: "destructive tools are never allowed" }
  - { match: "issue_refund", action: approval, when: { arg: amount, op: gt, value: 5000 },
      reason: "refunds over 5,000 BDT need a human" }
  - { match: "*",          action: allow }
"""

# The same policy, but the big-refund threshold is 50 BDT instead of 5,000.
TIGHTER = GOOD.replace("value: 5000", "value: 50")

BROKEN_YAML = """
defaults:
  budget_usd: 0.50
tools:
  - { match: "delete_*", action: deny
"""


@pytest.fixture
def policy_file(tmp_path):
    """A policy file on disk that a test can edit."""
    path = tmp_path / "policies.yaml"
    path.write_text(GOOD, encoding="utf-8")
    return path


# ── the validator ─────────────────────────────────────────────────────────────


def test_a_good_policy_has_no_errors():
    assert validate_yaml(GOOD) == []


def test_a_bad_operator_names_the_path_and_the_allowed_values():
    errors = validate_yaml(GOOD.replace("op: gt", "op: greater_than"))
    assert errors == ["tools[1].when.op: must be one of gt, gte, lt, lte, eq, ne, contains"]


def test_a_bad_action_names_the_path():
    errors = validate_yaml(GOOD.replace("action: deny", "action: block"))
    assert "tools[0].action: must be one of allow, deny, approval" in errors


def test_a_bad_budget_names_the_path():
    errors = validate_yaml(GOOD.replace("budget_usd: 0.50", "budget_usd: -1"))
    assert "defaults.budget_usd: must be a number > 0" in errors


def test_a_bad_agent_budget_names_the_path():
    errors = validate_yaml("agents:\n  delta: { budget_usd: zero }\n")
    assert "agents.delta.budget_usd: must be a number" in errors


def test_a_bad_on_trip_names_the_path():
    errors = validate_yaml("defaults:\n  on_trip: explode\n")
    assert "defaults.on_trip: must be one of pause, kill" in errors


def test_an_unknown_key_is_reported():
    errors = validate_yaml("defaults:\n  budget_usd: 0.5\n  budget: 1\n")
    assert "defaults.budget: is not a known setting" in errors


def test_a_when_without_an_op_is_reported():
    errors = validate_yaml("tools:\n  - { match: 'x', action: deny, when: { arg: a, value: 1 } }\n")
    assert "tools[0].when.op: is required" in errors


def test_broken_yaml_is_one_readable_error_not_a_traceback():
    errors = validate_yaml(BROKEN_YAML)
    assert len(errors) == 1
    assert errors[0].startswith("policy: not valid YAML")


def test_an_empty_file_is_a_valid_empty_policy():
    assert validate_yaml("") == []
    assert validate_yaml("{}") == []


def test_a_file_that_is_not_a_mapping_is_rejected():
    assert validate(["not", "a", "policy"]) != []


# ── the manager: swapping a good file ────────────────────────────────────────


def test_the_manager_starts_with_the_policy_it_was_given(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    assert m.view()["version"] == version_of(GOOD)
    assert m.view()["source"] == str(policy_file)
    assert m.view()["last_error"] == ""


def test_a_changed_file_is_swapped_in(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    policy_file.write_text(TIGHTER, encoding="utf-8")
    # make sure the mtime really changed (a fast test can write within the same tick)
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    result = m.check()
    assert result.changed and result.loaded
    # the threshold moved from 5,000 to 50, so a 100 BDT refund now needs a human
    assert m.policy.decide_tool("issue_refund", {"amount": 100})[0] == "approval"
    assert m.policy.decide_tool("issue_refund", {"amount": 10})[0] == "allow"


def test_an_unchanged_file_is_not_reloaded(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    result = m.check()
    assert not result.changed and not result.loaded
    assert m.reload_count == 0


def test_the_version_changes_with_the_file(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    before = m.policy.version
    policy_file.write_text(TIGHTER, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    m.check()
    assert m.policy.version != before
    assert len(m.policy.version) == 12


def test_a_reload_records_an_action(sim, policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file), store=sim.store)
    policy_file.write_text(TIGHTER, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    m.check()
    actions = [a for a in sim.store.recent_actions() if a["action"] == "POLICY_RELOAD"]
    assert len(actions) == 1
    assert "rule" in actions[0]["reason"] or "budget" in actions[0]["reason"]


# ── the manager: rejecting a broken file ──────────────────────────────────────


def test_a_broken_file_keeps_the_last_good_policy(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    policy_file.write_text(BROKEN_YAML, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    result = m.check()
    assert result.changed and not result.loaded
    assert result.errors
    # the good policy is still in force
    assert m.policy.decide_tool("delete_all", {})[0] == "deny"
    assert m.policy.decide_tool("issue_refund", {"amount": 6000})[0] == "approval"


def test_a_broken_file_raises_a_critical_alert(sim, policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file), store=sim.store)
    policy_file.write_text(BROKEN_YAML, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    m.check()
    alerts = [a for a in sim.store.recent_alerts() if a["rule"] == "policy_invalid"]
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert "YAML" in alerts[0]["message"]


def test_the_last_error_is_shown_until_a_good_file_arrives(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    policy_file.write_text(BROKEN_YAML, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    m.check()
    assert m.view()["last_error"]
    policy_file.write_text(TIGHTER, encoding="utf-8")
    os.utime(policy_file, (time.time() + 4, time.time() + 4))
    m.check()
    assert m.view()["last_error"] == ""


def test_a_deleted_file_keeps_the_last_good_policy(policy_file):
    p = Policy.load(str(policy_file))
    m = PolicyManager(p, str(policy_file))
    policy_file.unlink()
    result = m.check()
    assert not result.loaded
    assert m.policy.decide_tool("delete_all", {})[0] == "deny"


# ── the engine picks it up within 2 ticks ─────────────────────────────────────


def make_engine(cfg, policy_path):
    """An engine over a real policy file, with the fake fleet."""
    from brain.engine import Engine
    from brain.judge import Judge
    from shared.mocks.fake_fleet import FakeFleet
    from shared.store import LocalStore

    store = LocalStore(":memory:")
    fleet = FakeFleet(store, auto_rogue=None, start=1000.0)
    policy = Policy.load(str(policy_path))
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True, policy_path=str(policy_path))
    return store, fleet, engine


def test_editing_the_policy_changes_a_tool_decision_within_two_ticks(cfg, policy_file):
    """The acceptance case: edit the file, and the gate decides differently — no restart."""
    store, fleet, engine = make_engine(cfg, policy_file)

    # a 100 BDT refund is allowed by the policy as it stands
    assert engine.policy.decide_tool("issue_refund", {"amount": 100})[0] == "allow"

    # the operator tightens the threshold to 50 BDT
    policy_file.write_text(TIGHTER, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))

    now = 1000.0
    for _ in range(2):
        now += 1
        fleet.step(now)
        engine.tick(now)

    # the new rule is in force
    assert engine.policy.decide_tool("issue_refund", {"amount": 100})[0] == "approval"
    # and the tool gate (which asks the API, which asks the live policy) agrees
    from brain import service
    call = service.request_tool_call(store, engine.policy_manager.policy, "delta", "issue_refund",
                                     {"amount": 100}, 1.0)
    assert call["decision"] == "pending"   # approval → a human decides


def test_a_broken_policy_file_does_not_take_the_guard_down(cfg, policy_file):
    """The last good policy keeps working, and the alert says what is wrong."""
    store, fleet, engine = make_engine(cfg, policy_file)
    policy_file.write_text(BROKEN_YAML, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))

    now = 1000.0
    for _ in range(2):
        now += 1
        fleet.step(now)
        engine.tick(now)

    assert engine.policy.decide_tool("delete_all", {})[0] == "deny"
    alerts = [a for a in store.recent_alerts() if a["rule"] == "policy_invalid"]
    assert alerts and alerts[0]["severity"] == "critical"


def test_the_engine_keeps_running_after_a_broken_policy_file(cfg, policy_file):
    """A broken policy must never take the engine down."""
    store, fleet, engine = make_engine(cfg, policy_file)
    policy_file.write_text(BROKEN_YAML, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    now = 1000.0
    for _ in range(3):
        now += 1
        fleet.step(now)
        engine.tick(now)   # must not raise
    assert engine.breakers  # the engine is still watching


def test_the_reload_can_be_switched_off(cfg, policy_file):
    cfg = replace(cfg, policy_reload_enabled=False)
    store, fleet, engine = make_engine(cfg, policy_file)
    policy_file.write_text(TIGHTER, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    now = 1000.0
    for _ in range(3):
        now += 1
        fleet.step(now)
        engine.tick(now)
    assert engine.policy.decide_tool("issue_refund", {"amount": 100})[0] == "allow"


# ── the API ───────────────────────────────────────────────────────────────────


def client(sim, cfg, manager=None):
    from fastapi.testclient import TestClient

    from brain.api import create_app

    return TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback", policy_manager=manager))


def test_the_api_serves_the_policy(sim, cfg):
    c = client(sim, cfg)
    view = c.get("/v1/policy").json()
    assert set(view) == {"version", "loaded_at", "source", "defaults", "agents", "tools", "last_error"}
    assert view["defaults"]["budget_usd"] == 0.5
    assert view["defaults"]["on_trip"] == "pause"
    assert view["agents"]["delta"]["budget_usd"] == 0.2
    assert [t["match"] for t in view["tools"]][0] == "delete_*"


def test_the_validate_endpoint_returns_path_errors(sim, cfg):
    c = client(sim, cfg)
    bad = GOOD.replace("op: gt", "op: nope")
    res = c.post("/v1/policy/validate", json={"yaml": bad}).json()
    assert res["ok"] is False
    assert res["errors"] == ["tools[1].when.op: must be one of gt, gte, lt, lte, eq, ne, contains"]
    good = c.post("/v1/policy/validate", json={"yaml": GOOD}).json()
    assert good["ok"] is True and good["errors"] == []


def test_the_reload_endpoint_re_reads_the_file(sim, cfg, policy_file):
    from brain.policy_reload import PolicyManager

    manager = PolicyManager(Policy.load(str(policy_file)), str(policy_file), store=sim.store)
    c = client(sim, cfg, manager=manager)
    before = c.get("/v1/policy").json()["version"]

    policy_file.write_text(TIGHTER, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    res = c.post("/v1/policy/reload").json()
    assert res["ok"] is True
    assert res["policy"]["version"] != before


def test_the_reload_endpoint_reports_a_broken_file(sim, cfg, policy_file):
    from brain.policy_reload import PolicyManager

    manager = PolicyManager(Policy.load(str(policy_file)), str(policy_file), store=sim.store)
    c = client(sim, cfg, manager=manager)
    policy_file.write_text(BROKEN_YAML, encoding="utf-8")
    import os
    os.utime(policy_file, (time.time() + 2, time.time() + 2))
    res = c.post("/v1/policy/reload").json()
    assert res["ok"] is False
    assert res["errors"]
    assert res["policy"]["last_error"]


# ── the MCP server ────────────────────────────────────────────────────────────


def test_the_mcp_server_exposes_get_policy_and_validate_policy():
    import asyncio

    from brain import mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert "get_policy" in names
    assert "validate_policy" in names


def test_the_mcp_policy_tools_are_read_only():
    import asyncio

    from brain import mcp_server

    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert tools["get_policy"].annotations.read_only_hint is True
    assert tools["validate_policy"].annotations.read_only_hint is True


# ── the one-line diff summary ─────────────────────────────────────────────────


def test_the_summary_says_what_changed():
    old = Policy.from_dict({"defaults": {"budget_usd": 0.5}, "tools": [{"match": "a", "action": "allow"}]})
    new = Policy.from_dict({"defaults": {"budget_usd": 1.0}, "tools": [{"match": "a", "action": "deny"},
                                                                   {"match": "b", "action": "allow"}]})
    text = summarize(old, new)
    assert "budget" in text
    assert "+1 rule" in text


def test_the_summary_of_an_unchanged_policy_says_so():
    p = Policy.from_dict({"defaults": {"budget_usd": 0.5}})
    assert "same rules" in summarize(p, p)


# ── mock parity (the dashboard must not be able to tell the two apart) ─────────


def test_the_mock_and_the_real_api_serve_the_same_policy(sim, cfg):
    from fastapi.testclient import TestClient

    from brain.api import create_app
    from shared.mocks.mock_api import app as mock_app

    real = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback"))
    mock = TestClient(mock_app)
    r, m = real.get("/v1/policy").json(), mock.get("/v1/policy").json()
    assert set(r) == set(m)
    assert set(r["defaults"]) == set(m["defaults"])
    assert r["defaults"]["budget_usd"] == m["defaults"]["budget_usd"]
    assert r["agents"] == m["agents"]


def test_the_mock_and_the_real_api_validate_a_policy_the_same_way(sim, cfg):
    """The dashboard's "check my policy" button must behave the same against both."""
    from fastapi.testclient import TestClient

    from brain.api import create_app
    from shared.mocks.mock_api import app as mock_app

    real = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback"))
    mock = TestClient(mock_app)
    good = "defaults:\n  budget_usd: 0.5\ntools:\n  - { match: '*', action: allow }\n"
    bad = "tools:\n  - { match: '*', action: block }\n"
    for api in (real, mock):
        ok = api.post("/v1/policy/validate", json={"yaml": good}).json()
        assert ok["ok"] is True and ok["errors"] == []
        broken = api.post("/v1/policy/validate", json={"yaml": bad}).json()
        assert broken["ok"] is False
        assert "tools[0].action: must be one of allow, deny, approval" in broken["errors"]
