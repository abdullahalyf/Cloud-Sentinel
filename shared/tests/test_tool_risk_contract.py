"""
The learned tool risk (A14) — the contract side.

Three things are pinned here:

  1. **What counts as an approval.** Only a *human* answer teaches the brain to stop
     asking. A policy allow is the rules doing their job; an MCP answer is another
     agent's opinion. Neither is a person saying yes.
  2. **That a denial is a veto.** A call a human refused is never auto-approved, however
     many times somebody else later said yes.
  3. **The shape** — the mock API and the real API must return the same fields.

The mock leads the real API here (the contract lands the mock first, the brain branch
follows), so these tests are about the shared builder and the mock's endpoint.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

from shared.contracts import (TOOL_RISK_AUTO_APPROVE_AFTER, tool_risk_entry, tool_risk_from_history,
                              tool_risk_signature, tool_risk_view)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


def _client() -> TestClient:
    return TestClient(mock_app)


def call(agent_id="delta", tool="issue_refund", args=None, decision="allow", decided_by="human"):
    return {"agent_id": agent_id, "tool_name": tool, "args": args if args is not None else {"amount": 1000},
            "decision": decision, "decided_by": decided_by}


# ── what counts as an approval ──────────────────────────────────────────────
def test_five_human_approvals_auto_approve():
    history = [call() for _ in range(5)]
    entries = tool_risk_from_history(history)
    assert len(entries) == 1
    assert entries[0]["approvals"] == 5
    assert entries[0]["auto_approved"] is True


def test_four_human_approvals_are_not_enough():
    entries = tool_risk_from_history([call() for _ in range(4)])
    assert entries[0]["approvals"] == 4
    assert entries[0]["auto_approved"] is False


def test_a_policy_allow_does_not_count():
    """The rules allowing a call is not a person trusting it."""
    entries = tool_risk_from_history([call(decided_by="policy") for _ in range(10)])
    assert entries == []


def test_an_mcp_answer_does_not_count():
    """Another agent's opinion is not a human saying yes."""
    entries = tool_risk_from_history([call(decided_by="mcp") for _ in range(10)])
    assert entries == []


def test_only_human_answers_are_counted():
    history = ([call(decided_by="policy")] * 5 + [call(decided_by="human")] * 4
               + [call(decided_by="mcp")] * 6)
    entries = tool_risk_from_history(history)
    assert entries[0]["approvals"] == 4
    assert entries[0]["auto_approved"] is False


# ── a denial is a veto ───────────────────────────────────────────────────────
def test_a_denial_vetoes_the_call():
    """A person who refused this call has said something about it."""
    history = [call()] * 5 + [call(decision="deny")]
    entries = tool_risk_from_history(history)
    assert entries[0]["denials"] == 1
    assert entries[0]["auto_approved"] is False


def test_the_entry_keeps_both_counts():
    history = [call()] * 5 + [call(decision="deny")]
    entry = tool_risk_from_history(history)[0]
    assert entry["approvals"] == 5
    assert entry["denials"] == 1


def test_a_denial_with_no_approval_is_still_an_entry():
    entries = tool_risk_from_history([call(decision="deny")])
    assert len(entries) == 1
    assert entries[0]["approvals"] == 0
    assert entries[0]["denials"] == 1
    assert entries[0]["auto_approved"] is False


# ── the identity of a call ───────────────────────────────────────────────────
def test_the_signature_does_not_depend_on_the_key_order():
    """A refund of 500 for order 4471 is the same call however the JSON was written."""
    assert tool_risk_signature("issue_refund", {"a": 1, "b": 2}) == \
        tool_risk_signature("issue_refund", {"b": 2, "a": 1})


def test_different_arguments_are_different_calls():
    assert tool_risk_signature("issue_refund", {"amount": 1000}) != \
        tool_risk_signature("issue_refund", {"amount": 1001})


def test_different_tools_are_different_calls():
    assert tool_risk_signature("issue_refund", {"amount": 1000}) != \
        tool_risk_signature("send_email", {"amount": 1000})


def test_different_agents_are_scored_separately():
    """One agent's trust is not another agent's trust."""
    history = [call(agent_id="delta")] * 5 + [call(agent_id="gamma")] * 2
    entries = tool_risk_from_history(history)
    by_agent = {e["agent_id"]: e for e in entries}
    assert by_agent["delta"]["auto_approved"] is True
    assert by_agent["gamma"]["auto_approved"] is False


def test_a_pending_call_is_not_an_answer():
    """A call nobody has answered yet teaches nothing."""
    entries = tool_risk_from_history([call(decision="pending", decided_by="")])
    assert entries == []


def test_a_rewrite_is_not_an_approval():
    """A rewritten call was not approved as it stands."""
    entries = tool_risk_from_history([call(decision="rewrite")])
    assert entries == []


# ── the shape ────────────────────────────────────────────────────────────────
def test_the_entry_has_every_field_the_contract_names():
    entry = tool_risk_entry("delta", "issue_refund", {"amount": 1000}, 5, 0)
    for field in ("agent_id", "tool_name", "args", "signature", "approvals", "denials",
                  "threshold", "auto_approved", "reason"):
        assert field in entry, f"the entry has no {field}"


def test_the_view_has_every_field_the_contract_names():
    view = tool_risk_view([])
    for field in ("entries", "counts", "threshold"):
        assert field in view, f"the view has no {field}"
    for field in ("entries", "auto_approved", "denied"):
        assert field in view["counts"], f"counts has no {field}"


def test_the_view_counts_what_it_holds():
    entries = [tool_risk_entry("delta", "issue_refund", {"amount": 1000}, 5, 0),
               tool_risk_entry("delta", "send_email", {"amount": 1}, 1, 0),
               tool_risk_entry("delta", "run_sql", {"q": "x"}, 0, 1)]
    view = tool_risk_view(entries)
    assert view["counts"]["entries"] == 3
    assert view["counts"]["auto_approved"] == 1
    assert view["counts"]["denied"] == 1


def test_the_threshold_is_five():
    assert TOOL_RISK_AUTO_APPROVE_AFTER == 5
    assert tool_risk_view([])["threshold"] == 5


def test_the_reason_says_why():
    """A client must never have to guess why a call was or was not auto-approved."""
    ready = tool_risk_entry("delta", "issue_refund", {"amount": 1000}, 5, 0)
    assert "5" in ready["reason"]
    not_ready = tool_risk_entry("delta", "issue_refund", {"amount": 1000}, 2, 0)
    assert "3 more" in not_ready["reason"]


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_tool_risk_endpoint():
    r = _client().get("/v1/tool-risk")
    assert r.status_code == 200
    body = r.json()
    for field in ("entries", "counts", "threshold"):
        assert field in body, f"the mock's tool-risk has no {field}"


def test_the_mock_shows_a_call_that_is_past_the_threshold():
    entries = _client().get("/v1/tool-risk").json()["entries"]
    approved = [e for e in entries if e["auto_approved"]]
    assert approved, "the mock should show a call that is past the threshold"


def test_the_mock_can_filter_by_agent():
    entries = _client().get("/v1/tool-risk?agent_id=delta").json()["entries"]
    assert entries
    assert all(e["agent_id"] == "delta" for e in entries)
