"""
The brain-side tests for B7's tamper-evident audit log.

An audit log that can be edited after the fact is not an audit log. This one
is **hash-chained**: every entry carries the hash of the entry before it, so
an edit in the middle does not just change that entry — it breaks every link
after it. Deleting an entry breaks the chain the same way.

Seven things must hold:

- the chain **links** — the hash of an entry is the previous entry's hash plus
  its own content;
- a **tampered** entry is caught by the verify command, and the command says
  **which** entry;
- **deleting** an entry from the middle is caught too;
- a chain with **no entries** verifies — nothing has happened yet, and that is a fact;
- **every** brain decision and **every** human action is in the chain (a PAUSE
  by a human, a TOOL_DENY by the policy, an AUTO_HEAL);
- the verify command **exits non-zero** on a broken chain, so it can be a CI job;
- the **flag off** → nothing is chained and the endpoint says so, without failing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from brain import audit as brain_audit
from brain import service
from brain.api import create_app
from brain.policy import Policy
from shared.config import Settings, settings
from shared.contracts import AUDIT_GENESIS, audit_hash
from shared.store import LocalStore


@pytest.fixture
def store():
    return LocalStore(":memory:")


@pytest.fixture
def on():
    """The settings with the audit chain on."""
    return replace(settings, audit_enabled=True)


# ── the chain links ─────────────────────────────────────────────────────────
def test_the_chain_links(store):
    """Each entry's hash is the previous entry's hash plus this entry's content."""
    first = brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE",
                               reason="semantic loop")
    second = brain_audit.append(store, agent_id="beta", actor="dashboard", action="RESUME",
                                reason="by hand")

    assert first["seq"] == 1 and second["seq"] == 2
    assert first["prev_hash"] == AUDIT_GENESIS
    # the second entry says "the entry before me" and means it
    assert second["prev_hash"] == first["hash"]
    # and each hash is the content hashed
    assert first["hash"] == audit_hash(first)
    assert second["hash"] == audit_hash(second)


def test_the_chain_starts_at_one(store):
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="r")
    entries = brain_audit.read_chain(store)
    assert [e["seq"] for e in entries] == [1]


def test_the_entries_are_ordered_oldest_first(store):
    for i in range(5):
        brain_audit.append(store, agent_id="beta", actor="rules", action="WARN", reason=f"r{i}")
    entries = brain_audit.read_chain(store)
    assert [e["reason"] for e in entries] == ["r0", "r1", "r2", "r3", "r4"]


# ── the tampering is caught ─────────────────────────────────────────────────
def test_a_tampered_entry_is_caught_and_the_command_says_which_one(store):
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")
    brain_audit.append(store, agent_id="beta", actor="rules", action="KILL", reason="worse")
    brain_audit.append(store, agent_id="beta", actor="rules", action="WARN", reason="note")

    # somebody edits the reason of the second entry, in the database, after the fact
    rows = store.audit_entries(limit=10)
    second = [r for r in rows if r["seq"] == 2][0]
    store._conn.execute("update audit_log set reason = ? where seq = 2", ("a nicer reason",))
    store._conn.commit()

    result = brain_audit.verify(brain_audit.read_chain(store))
    assert result["ok"] is False
    assert result["broken_at"] == 2
    assert "2" in result["reason"]


def test_deleting_an_entry_from_the_middle_is_caught(store):
    for i in range(4):
        brain_audit.append(store, agent_id="beta", actor="rules", action="WARN", reason=f"r{i}")

    # somebody deletes the second entry
    store._conn.execute("delete from audit_log where seq = 2")
    store._conn.commit()

    result = brain_audit.verify(brain_audit.read_chain(store))
    assert result["ok"] is False
    assert result["broken_at"] == 3
    assert "sequence" in result["reason"]


def test_an_empty_chain_verifies(store):
    """Nothing has happened yet — and that is a fact, not a broken chain."""
    result = brain_audit.verify(brain_audit.read_chain(store))
    assert result["ok"] is True
    assert result["entries"] == 0
    assert result["head_hash"] == AUDIT_GENESIS
    assert result["broken_at"] is None


def test_an_intact_chain_verifies(store):
    for i in range(3):
        brain_audit.append(store, agent_id="beta", actor="rules", action="WARN", reason=f"r{i}")
    result = brain_audit.verify(brain_audit.read_chain(store))
    assert result["ok"] is True and result["entries"] == 3
    assert result["broken_at"] is None


def test_the_chain_is_append_only(store):
    """Nothing in the chain is ever updated — an entry is added, never rewritten."""
    for i in range(3):
        brain_audit.append(store, agent_id="beta", actor="rules", action="WARN", reason=f"r{i}")
    before = brain_audit.read_chain(store)

    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="new")

    after = brain_audit.read_chain(store)
    # the first three are untouched
    for old, new in zip(before, after):
        assert old == new
    assert len(after) == len(before) + 1


# ── the kinds ───────────────────────────────────────────────────────────────
def test_the_kind_says_who_did_it(store):
    assert brain_audit.kind_for("rules") == "decision"
    assert brain_audit.kind_for("brain:autoheal") == "decision"
    assert brain_audit.kind_for("policy") == "policy"
    assert brain_audit.kind_for("human") == "human"
    assert brain_audit.kind_for("dashboard") == "human"
    assert brain_audit.kind_for("mcp") == "human"


# ── every decision and every human action is in the chain ───────────────────
def test_the_brain_decisions_are_in_the_chain(store, on):
    """A PAUSE the brain decided on its own, and an AUTO_HEAL, are both in it."""
    from brain.engine import Engine
    from brain.judge import Judge
    from shared.mocks.fake_fleet import FakeFleet

    cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="",
                  audit_enabled=True)
    fleet = FakeFleet(store, auto_rogue=None, start=1000.0)
    engine = Engine(store, fleet, Judge(cfg), Policy.load("brain/policies.yaml"), cfg,
                    sync_judge=True)
    fleet.gate = lambda a, t, args, v: service.request_tool_call(
        store, engine.policy, a, t, args, v, audit_enabled=True)

    # a runaway that the rules will pause
    fleet.go_rogue("beta", "paraphrase_loop", 1001.0)
    for i in range(40):
        fleet.step(1001.0 + i)
        engine.tick(1001.0 + i)

    entries = brain_audit.read_chain(store)
    assert entries, "the brain decided something, so the chain must not be empty"
    kinds = {e["kind"] for e in entries}
    assert "decision" in kinds
    assert any(e["agent_id"] == "beta" for e in entries)
    # and the chain still verifies after all of that
    assert brain_audit.verify(entries)["ok"] is True


def test_a_human_memory_edit_is_in_the_chain(store):
    """The `human` kind: a person edited an agent's memory."""
    service.save_memory(store, "beta", {"k": "v"}, "human", "the order was cancelled",
                        None, audit_enabled=True)
    entries = brain_audit.read_chain(store)
    assert len(entries) == 1
    assert entries[0]["kind"] == "human"
    assert entries[0]["actor"] == "human"
    assert entries[0]["action"] == "MEMORY_EDIT"


def test_a_policy_deny_is_in_the_chain(store):
    """The `policy` kind: the tool gate denied a call."""
    policy = Policy.load("brain/policies.yaml")
    service.request_tool_call(store, policy, "delta", "delete_all_orders",
                              {"order_id": 1}, 410.0, audit_enabled=True)
    entries = brain_audit.read_chain(store)
    assert len(entries) == 1
    assert entries[0]["kind"] == "policy"
    assert entries[0]["actor"] == "policy"
    assert entries[0]["action"] == "TOOL_DENY"


def test_an_auto_heal_is_in_the_chain(store):
    """The `decision` kind: the brain changed an agent's memory on its own."""
    from brain.heal import Patch, propose

    pid = propose(store, "beta", Patch("memory_patch", ops=[{"op": "set", "key": "order_4471",
                                                            "value": "cancelled"}]),
                  0.9, 1, 1, reason="the belief keeps it looping")
    from brain.heal import decide

    decide(store, pid, "apply", "brain:autoheal", "confident and valid", audit_enabled=True)
    entries = brain_audit.read_chain(store)
    assert len(entries) == 1
    assert entries[0]["kind"] == "decision"
    assert entries[0]["action"] == "AUTO_HEAL"
    assert entries[0]["actor"] == "brain:autoheal"


def test_a_human_tool_decision_is_in_the_chain(store):
    """A person deciding a held tool call is a `human` action."""
    policy = Policy.load("brain/policies.yaml")
    call = service.request_tool_call(store, policy, "delta", "issue_refund",
                                     {"amount": 50000, "order_id": 1}, 410.0)
    service.decide_tool_call(store, call["id"], "rewrite", {"amount": 500}, "human",
                              "too big", audit_enabled=True)
    entries = brain_audit.read_chain(store)
    assert len(entries) == 1
    assert entries[0]["kind"] == "human"
    assert entries[0]["action"] == "TOOL_REWRITE"


# ── the flag off ────────────────────────────────────────────────────────────
def test_with_the_flag_off_nothing_is_chained(store):
    service.save_memory(store, "beta", {"k": "v"}, "human", "why", None, audit_enabled=False)
    assert brain_audit.read_chain(store) == []
    # and the action is still written — the behaviour before the chain existed
    assert store.recent_actions(1)


def test_the_action_is_written_even_when_the_chain_is_off(store):
    brain_audit.record_action(store, agent_id="beta", action="PAUSE", actor="rules",
                               reason="loop", enabled=False)
    assert len(store.recent_actions(1)) == 1
    assert brain_audit.read_chain(store) == []


# ── the endpoint ────────────────────────────────────────────────────────────
def _client(store, cfg):
    return TestClient(create_app(store, Policy.load("brain/policies.yaml"), cfg, "fake", "fallback"))


def test_the_endpoint_serves_the_chain_and_its_head_hash(store, on):
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")
    body = _client(store, on).get("/v1/audit").json()

    assert body["enabled"] is True
    assert body["valid"] is True
    assert body["broken_at"] is None
    assert len(body["entries"]) == 1
    assert body["head_hash"] == body["entries"][0]["hash"]
    assert body["counts"]["entries"] == 1
    assert body["counts"]["decisions"] == 1


def test_the_endpoint_with_the_flag_off_says_so_without_failing(store):
    """Not a 404: an operator asking "is the log tamper-proof?" deserves an answer.

    The flag decides whether the chain is *written*, not whether it is *read* —
    a chain written before the flag was turned off is still a chain, and hiding
    it would be the one thing a tamper-evident log must never do.
    """
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")
    off = replace(settings, audit_enabled=False)
    body = _client(store, off).get("/v1/audit").json()

    assert body["enabled"] is False
    assert len(body["entries"]) == 1
    assert body["valid"] is True


def test_the_endpoint_with_the_flag_off_and_no_chain_says_so(store):
    """The plain case: the flag off, nothing was ever chained, and the endpoint
    answers honestly instead of failing."""
    off = replace(settings, audit_enabled=False)
    body = _client(store, off).get("/v1/audit").json()

    assert body["enabled"] is False
    assert body["entries"] == []
    assert body["valid"] is True
    assert body["counts"]["entries"] == 0


def test_the_endpoint_reports_a_broken_chain(store, on):
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")
    brain_audit.append(store, agent_id="beta", actor="rules", action="KILL", reason="worse")
    store._conn.execute("update audit_log set reason = ? where seq = 2", ("a nicer reason",))
    store._conn.commit()

    body = _client(store, on).get("/v1/audit").json()
    assert body["valid"] is False
    assert body["broken_at"] == 2


# ── the verify command ──────────────────────────────────────────────────────
def _run_verify(db, command="verify"):
    return subprocess.run([sys.executable, "-m", "brain.audit", command, "--db", db],
                          capture_output=True, text=True)


def test_the_verify_command_exits_zero_on_an_intact_chain(tmp_path):
    db = str(tmp_path / "audit.db")
    store = LocalStore(db)
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")

    result = _run_verify(db)
    assert result.returncode == 0
    assert "intact" in result.stdout


def test_the_verify_command_exits_non_zero_on_a_broken_chain(tmp_path):
    """The exit code is the point: a verify command that always exits 0 is a command
    nobody can trust."""
    db = str(tmp_path / "audit.db")
    store = LocalStore(db)
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")
    brain_audit.append(store, agent_id="beta", actor="rules", action="KILL", reason="worse")
    store._conn.execute("update audit_log set reason = ? where seq = 2", ("a nicer reason",))
    store._conn.commit()

    result = _run_verify(db)
    assert result.returncode == 1
    assert "BROKEN" in result.stderr
    assert "2" in result.stderr


def test_the_verify_command_exits_zero_on_an_empty_chain(tmp_path):
    db = str(tmp_path / "audit.db")
    LocalStore(db)
    result = _run_verify(db)
    assert result.returncode == 0


def test_the_verify_command_can_print_json(tmp_path):
    db = str(tmp_path / "audit.db")
    store = LocalStore(db)
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")

    result = _run_verify(db, command="verify")
    payload = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    # without --json it prints prose; with it, JSON. Both must work.
    assert result.returncode == 0

    result_json = subprocess.run(
        [sys.executable, "-m", "brain.audit", "verify", "--db", db, "--json"],
        capture_output=True, text=True)
    payload = json.loads(result_json.stdout)
    assert payload["ok"] is True and payload["entries"] == 1


def test_the_show_command_lists_the_chain(tmp_path):
    db = str(tmp_path / "audit.db")
    store = LocalStore(db)
    brain_audit.append(store, agent_id="beta", actor="rules", action="PAUSE", reason="loop")

    result = _run_verify(db, command="show")
    assert result.returncode == 0
    assert "PAUSE" in result.stdout
