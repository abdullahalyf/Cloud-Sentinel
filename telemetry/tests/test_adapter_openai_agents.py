"""OpenAI Agents adapter, end to end with an offline fake model: Runner -> processor -> OTel -> collector normalizer."""
import json

import pytest

_agents = pytest.importorskip("agents")
if not hasattr(_agents, "Agent"):   # some other folder called "agents" is on the path, not openai-agents
    pytest.skip("openai-agents is not installed", allow_module_level=True)

import cloudsentinel as cs  # noqa: E402
from agents import Agent, Model, ModelResponse, Runner, Usage, function_tool, set_trace_processors  # noqa: E402
from agents.tracing import generation_span  # noqa: E402
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText  # noqa: E402

from cloudsentinel.adapters.openai_agents import CloudSentinelProcessor, guard  # noqa: E402


class FakeModel(Model):
    def __init__(self, script):
        self.script = list(script)

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, *, previous_response_id=None, conversation_id=None, prompt=None):
        with generation_span(model="fake-model", usage={"input_tokens": 100, "output_tokens": 20}):
            out = self.script.pop(0)
        return ModelResponse(output=out, usage=Usage(requests=1, input_tokens=100, output_tokens=20,
                                                     total_tokens=120), response_id=None)

    def stream_response(self, *a, **k):
        raise NotImplementedError


def _call(name, args):
    return [ResponseFunctionToolCall(arguments=json.dumps(args), call_id="c-" + name, name=name, type="function_call")]


def _say(text):
    return [ResponseOutputMessage(id="m1", role="assistant", status="completed", type="message",
                                  content=[ResponseOutputText(text=text, type="output_text", annotations=[])])]


@pytest.fixture
def processor(captured, monkeypatch):
    p = CloudSentinelProcessor()
    set_trace_processors([p])
    return p


def _run(tool):
    refunds = Agent(name="refunds", instructions="x", tools=[tool],
                    model=FakeModel([_call("issue_refund", {"order_id": 4471, "amount": 50000}), _say("done")]))
    triage = Agent(name="triage", instructions="x", handoffs=[refunds],
                   model=FakeModel([_call("transfer_to_refunds", {})]))
    return Runner.run_sync(triage, "refund order 4471")


def test_spans_kinds_tokens_and_nesting(processor, captured, monkeypatch):
    calls = {"n": 0}

    @function_tool
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        calls["n"] += 1
        return "refunded"

    assert _run(issue_refund).final_output == "done" and calls["n"] == 1
    rows = captured()
    ops = [r.operation for r in rows]
    assert ops.count("invoke_agent") == 1 and ops.count("chat") == 3
    assert ops.count("execute_tool") == 1
    chats = [r for r in rows if r.operation == "chat"]
    assert all((r.input_tokens, r.output_tokens) == (100, 20) and r.model == "fake-model" for r in chats)
    task = next(r for r in rows if r.operation == "invoke_agent")
    assert task.task_status == "success"
    nodes = [json.loads(r.detail) for r in rows if r.operation == "graph_node"]
    assert {n["node"] for n in nodes} == {"triage", "refunds"}
    assert all(n["framework"] == "openai-agents" for n in nodes)
    assert any(n["next"] == "refunds" for n in nodes)
    node_ids = {r.span_id for r in rows if r.operation == "graph_node"}
    tool = next(r for r in rows if r.operation == "execute_tool")
    assert tool.tool_name == "issue_refund" and tool.parent_span_id in node_ids


def test_big_refund_is_held_when_the_gate_denies(processor, captured, monkeypatch):
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"id": 1, "decision": "deny", "final_args": None}))
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    calls = {"n": 0}

    @function_tool
    @guard(value_usd=410.0, fail_closed=True)
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        calls["n"] += 1
        return "refunded"

    _run(issue_refund)
    assert calls["n"] == 0                       # the 50,000 refund never ran
    rows = captured()
    refund = next(r for r in rows if r.tool_name == "issue_refund")
    assert refund.status == "error"
    node_ids = {r.span_id for r in rows if r.operation == "graph_node"}
    assert refund.parent_span_id in node_ids
    assert next(r for r in rows if r.operation == "invoke_agent").task_status == "failure"


def test_gate_unreachable_fail_closed_denies(processor, captured, monkeypatch):
    import urllib.error

    def down(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(cs, "_api", down)
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: None)
    calls = {"n": 0}

    @function_tool
    @guard(value_usd=410.0, fail_closed=True)
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        calls["n"] += 1
        return "refunded"

    _run(issue_refund)
    assert calls["n"] == 0


def test_guard_checks_the_pause_before_the_gate(processor, captured, monkeypatch):
    order = []
    monkeypatch.setattr(cs, "wait_if_paused", lambda *a, **k: order.append("pause_check"))
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (order.append("gate"), (200, {"id": 1, "decision": "allow", "final_args": None}))[1])

    @function_tool
    @guard(value_usd=1.0)
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        order.append("body")
        return "refunded"

    _run(issue_refund)
    assert order[:3] == ["pause_check", "gate", "body"]


def test_a_killed_agent_stops_at_the_guard(processor, captured, monkeypatch):
    calls = {"n": 0}

    def killed(*a, **k):
        raise cs.AgentKilled("killed")

    monkeypatch.setattr(cs, "wait_if_paused", killed)

    @function_tool
    @guard(value_usd=1.0)
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order."""
        calls["n"] += 1
        return "refunded"

    _run(issue_refund)
    assert calls["n"] == 0
