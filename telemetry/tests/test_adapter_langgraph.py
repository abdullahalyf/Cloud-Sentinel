"""LangGraph adapter + demo agent, end to end: real graph → callback → OTel → collector normalizer → SpanRows."""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("langgraph")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import langgraph_refund_agent as demo  # noqa: E402

import cloudsentinel as cs  # noqa: E402


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(demo, "STEP_DELAY", 0)
    monkeypatch.setitem(demo.ROGUE, "on", False)
    return demo.build_graph(demo.SimChat())


def nodes(rows):
    return [json.loads(r.detail) for r in rows if r.operation == "graph_node"]


def test_healthy_run_emits_task_nodes_chat_and_gated_tools(agent, captured, mock_api):
    result = demo.run_once(agent, 4500)
    rows = captured()
    ops = [r.operation for r in rows]
    path = [n["node"] for n in sorted(nodes(rows), key=lambda n: n["step"])]
    assert path == ["classify", "lookup_order", "decide", "refund"]
    assert ops.count("invoke_agent") == 1 and ops.count("chat") == 2
    task = next(r for r in rows if r.operation == "invoke_agent")
    assert task.task_status == "success" and "refunded" in result["answer"]
    lookup = next(n for n in nodes(rows) if n["node"] == "lookup_order")
    assert lookup["next"] == "decide" and "status" in lookup["changed"] and lookup["framework"] == "langgraph"
    chat = next(r for r in rows if r.operation == "chat")
    assert chat.input_tokens > 0 and chat.model == "sim" and chat.prompt_preview
    tools = [r.tool_name for r in rows if r.operation == "execute_tool"]
    assert tools.count("orders_api") == 1 and tools.count("issue_refund") == 1   # guard(): no duplicate spans
    node_ids = {r.span_id for r in rows if r.operation == "graph_node"}
    assert all(r.parent_span_id in node_ids for r in rows if r.operation in ("chat", "execute_tool"))


def test_rogue_loop_is_visible_and_memory_fix_ends_it(agent, captured, mock_api, monkeypatch):
    demo.ROGUE["on"] = True
    mock_api.put("/v1/agents/test-agent/memory", json={"content": demo.BAD_BELIEF, "edited_by": "agent"})
    result = demo.run_once(agent, demo.BAD_ORDER, recursion_limit=12)
    assert result["answer"] == "gave up: recursion limit"
    rows = captured()
    path = [n["node"] for n in sorted(nodes(rows), key=lambda n: n["step"])]
    assert path[:5] == ["classify", "lookup_order", "retry", "lookup_order", "retry"]
    assert any(r.status == "error" for r in rows if r.tool_name == "orders_api")   # failing tool cycle
    task = next(r for r in rows if r.operation == "invoke_agent")
    assert task.task_status == "failure"
    # heal: a human fixes the belief → the next run moves on instead of looping
    mock_api.put("/v1/agents/test-agent/memory", json={"content": {"order_4471": "cancelled - skip it"},
                                                       "edited_by": "human"})
    assert "skipped" in demo.run_once(agent, demo.BAD_ORDER, recursion_limit=12)["answer"]


def test_big_refund_is_held_and_killed_agent_stops(agent, captured, mock_api, monkeypatch):
    monkeypatch.setattr(cs._s, "approval_timeout", 0.0)
    monkeypatch.setattr(demo, "BAD_ORDER", 4501)    # healthy status, but the 50,000 refund path
    result = demo.run_once(agent, 4501)
    assert "refund not done" in result["answer"]       # pending → nobody approved in time → denied
    refund = next(r for r in captured() if r.tool_name == "issue_refund")
    assert refund.status == "error"
    mock_api.post("/v1/agents/test-agent/commands", json={"command": "KILL"})  # mock: unknown agent, no state
    monkeypatch.setattr(cs, "wait_if_paused", lambda: (_ for _ in ()).throw(cs.AgentKilled("killed")))
    with pytest.raises(cs.AgentKilled):
        demo.run_once(agent, 4502)


def test_telemetry_errors_never_break_the_graph(agent, monkeypatch, mock_api, captured):
    monkeypatch.setattr(cs, "start_span", lambda *a, **k: 1 / 0)
    assert "answer" in demo.run_once(agent, 4503)
