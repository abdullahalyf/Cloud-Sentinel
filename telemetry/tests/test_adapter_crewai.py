"""CrewAI adapter + demo crew, end to end (skipped unless crewai is installed — CI job `adapters` installs it)."""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("crewai")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import crewai_support_crew as demo  # noqa: E402

import cloudsentinel as cs  # noqa: E402
from cloudsentinel.adapters import crewai as adapter  # noqa: E402


@pytest.fixture
def crew(captured, mock_api, monkeypatch):
    monkeypatch.setattr(cs._s, "approval_timeout", 0.0)
    demo.instrument(value_usd={"issue_refund": lambda a: a["amount"] / demo.BDT_PER_USD}, fail_closed=("issue_refund",))
    return demo.build_crew(demo.ScriptedLLM(model="sim"))


def test_crew_run_becomes_task_nodes_chats_and_tools(crew, captured):
    crew.kickoff(inputs={"ticket": "Order 4471 arrived broken, please refund 800 BDT"})
    adapter.flush()   # CrewAI runs event handlers on a thread pool: wait for them
    rows = captured()
    task = [r for r in rows if r.operation == "invoke_agent"]
    nodes = sorted((json.loads(r.detail) for r in rows if r.operation == "graph_node"), key=lambda d: d["step"])
    assert len(task) == 1 and task[0].task_status == "success"
    assert [n["node"] for n in nodes] == ["Triage", "Refunds"] and nodes[0]["framework"] == "crewai"
    assert "output" in nodes[1]["changed"]
    chats = [r for r in rows if r.operation == "chat"]
    assert len(chats) >= 3 and all(c.input_tokens > 0 and c.output_tokens > 0 for c in chats)
    tool = next(r for r in rows if r.operation == "execute_tool")
    assert tool.tool_name == "issue_refund" and tool.status == "ok"
    span_ids = {r.span_id for r in rows}
    assert all(r.parent_span_id in span_ids for r in rows if r.operation != "invoke_agent")  # one connected trace


def test_big_refund_is_blocked_by_the_gate_and_recorded(crew, captured, mock_api):
    crew.kickoff(inputs={"ticket": "Order 4471 arrived broken, please refund 50000 BDT"})
    adapter.flush()
    blocked = [r for r in captured() if r.operation == "execute_tool" and r.tool_name == "issue_refund"]
    assert blocked and blocked[0].status == "error" and blocked[0].error_type == "tool_timeout"
    held = mock_api.get("/v1/tool-calls?status=pending").json()["items"]
    assert any(c["args"].get("amount") == 50000 and c["agent_id"] == "test-agent" for c in held)


def test_done_before_start_is_still_recorded(captured):
    """The thread pool can run a 'completed' handler before its 'started' one; the span must not be lost."""
    listener = adapter.CloudSentinelListener.__new__(adapter.CloudSentinelListener)
    listener._spans, listener._crew, listener._step, listener._decisions, listener._early = {}, None, 0, {}, {}
    import threading
    listener._lock = threading.Lock()
    listener._close("llm|x", None, {cs.INPUT_TOKENS: 7, cs.OUTPUT_TOKENS: 3})          # done arrives first
    listener._open("llm|x", "chat sim", "chat", {cs.REQUEST_MODEL: "sim"})            # then the start
    chats = [r for r in captured() if r.operation == "chat"]
    assert len(chats) == 1 and chats[0].input_tokens == 7 and not listener._spans and not listener._early


def test_drain_records_a_completion_whose_start_never_came(captured):
    listener = adapter.CloudSentinelListener.__new__(adapter.CloudSentinelListener)
    listener._spans, listener._crew, listener._step, listener._decisions, listener._early = {}, None, 0, {}, {}
    import threading
    listener._lock = threading.Lock()
    listener._close("llm|y", None, {cs.INPUT_TOKENS: 5, cs.OUTPUT_TOKENS: 2},
                    start_late=lambda: listener._open("llm|y", "chat sim", "chat", {cs.REQUEST_MODEL: "sim"}))
    listener.drain()
    chats = [r for r in captured() if r.operation == "chat"]
    assert len(chats) == 1 and chats[0].output_tokens == 2 and not listener._early and not listener._spans
