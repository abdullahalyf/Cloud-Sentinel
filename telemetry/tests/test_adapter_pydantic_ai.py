"""Pydantic AI adapter with the offline TestModel: Agent -> OTel -> collector normalizer -> SpanRows."""
import json

import pytest

pytest.importorskip("pydantic_ai")

import cloudsentinel as cs  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

from cloudsentinel.adapters.pydanticai import guard, instrument  # noqa: E402


@pytest.fixture
def pai(captured, monkeypatch):
    monkeypatch.setattr(cs._s, "agent_id", "pai-agent")     # differs from the resource's service.name
    instrument()
    yield
    Agent.instrument_all(False)


def _agent(tool):
    agent = Agent(TestModel(), name="refunds")
    agent.tool_plain(tool)
    return agent


def _plain_tool(calls):
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        calls["n"] += 1
        return "refunded"
    return issue_refund


def test_spans_tokens_agent_id_and_tool_args(pai, captured):
    calls = {"n": 0}
    _agent(_plain_tool(calls)).run_sync("refund order 4471")
    rows = captured()
    ops = [r.operation for r in rows]
    assert ops.count("invoke_agent") == 1 and ops.count("chat") == 2 and ops.count("execute_tool") == 1
    assert all(r.agent_id == "pai-agent" for r in rows)           # set by the processor, not the resource
    chats = [r for r in rows if r.operation == "chat"]
    assert all(r.input_tokens > 0 and r.output_tokens > 0 for r in chats)
    tool = next(r for r in rows if r.operation == "execute_tool")
    assert tool.tool_name == "issue_refund" and "order_id" in json.loads(tool.tool_args)
    assert calls["n"] == 1


def test_known_limitation_chat_spans_have_no_prompt_hash(pai, captured):
    """Pydantic AI adds the messages when the span ends, so prompt-based loop detection cannot see them."""
    _agent(_plain_tool({"n": 0})).run_sync("refund order 4471")
    chats = [r for r in captured() if r.operation == "chat"]
    assert chats and all(not r.prompt_hash for r in chats)


def test_a_guarded_tool_gives_one_span_and_runs_when_the_gate_allows(pai, captured, monkeypatch):
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"id": 1, "decision": "allow", "final_args": None}))
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    calls = {"n": 0}
    guarded = guard(value_usd=410.0, fail_closed=True)(_plain_tool(calls))
    _agent(guarded).run_sync("refund order 4471")
    assert calls["n"] == 1
    assert [r.operation for r in captured()].count("execute_tool") == 1      # no duplicate span


def test_a_big_refund_is_held_when_the_gate_denies(pai, captured, monkeypatch):
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"id": 1, "decision": "deny", "final_args": None}))
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    calls = {"n": 0}
    guarded = guard(value_usd=410.0, fail_closed=True)(_plain_tool(calls))
    try:
        _agent(guarded).run_sync("refund order 4471")
    except Exception:       # whether Pydantic AI re-raises or feeds the error to the model is not asserted
        pass
    assert calls["n"] == 0


def test_the_gate_unreachable_with_fail_closed_denies(pai, captured, monkeypatch):
    import urllib.error

    def down(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(cs, "_api", down)
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    calls = {"n": 0}
    guarded = guard(value_usd=410.0, fail_closed=True)(_plain_tool(calls))
    try:
        _agent(guarded).run_sync("refund order 4471")
    except Exception:
        pass
    assert calls["n"] == 0


def test_guard_checks_the_pause_before_the_gate(pai, captured, monkeypatch):
    order = []
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: order.append("pause_check"))
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (order.append("gate"), (200, {"id": 1, "decision": "allow", "final_args": None}))[1])
    guarded = guard(value_usd=1.0)(_plain_tool({"n": 0}))
    _agent(guarded).run_sync("refund order 4471")
    assert order[:2] == ["pause_check", "gate"]


def test_a_rewrite_runs_the_tool_with_the_new_args(pai, captured, monkeypatch):
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"id": 1, "decision": "rewrite",
                                                           "final_args": {"order_id": 1, "amount": 5}}))
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    seen = []

    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        seen.append((order_id, amount))
        return "refunded"

    guarded = guard(value_usd=1.0)(issue_refund)
    _agent(guarded).run_sync("refund order 4471")
    assert seen == [(1, 5)]


def test_the_gate_decision_is_written_on_the_current_span(monkeypatch):
    import cloudsentinel.adapters.pydanticai as mod

    written = {}

    class FakeSpan:
        def set_attribute(self, key, value):
            written[key] = value

    monkeypatch.setattr(mod.otel_trace, "get_current_span", lambda: FakeSpan())
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"id": 1, "decision": "allow", "final_args": None}))
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    guarded = guard(value_usd=7.0)(lambda order_id, amount: "ok")
    guarded(order_id=1, amount=2)
    assert written[cs.CS_TOOL_DECISION] == "allow" and written[cs.CS_TOOL_VALUE_USD] == 7.0
