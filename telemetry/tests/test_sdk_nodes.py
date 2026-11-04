"""SDK: graph_node spans, preview_delta, gate(), wait_if_paused()."""
import json

import pytest

import cloudsentinel as cs


def test_node_span_reaches_the_collector_with_detail(captured, no_api):
    with cs.task("t"):
        with cs.node("lookup_order", step=3, framework="langgraph") as n:
            n.changed({"status": "x" * 200, "messages": [1, 2, 3]})
    rows = {r.operation: r for r in captured()}
    node = rows["graph_node"]
    detail = json.loads(node.detail)
    assert node.name == "graph_node lookup_order" and node.agent_id == "test-agent"
    assert detail["node"] == "lookup_order" and detail["step"] == 3 and detail["framework"] == "langgraph"
    assert len(detail["changed"]["status"]) <= 60 and detail["changed"]["messages"].startswith("3 items")
    assert node.parent_span_id == rows["invoke_agent"].span_id


def test_preview_delta_limits_keys_and_handles_non_dicts():
    big = cs.preview_delta({f"k{i}": i for i in range(20)})
    assert len(big) == 9 and big["…"] == "+12 more keys"
    assert cs.preview_delta("done") == {"value": "done"} and cs.preview_delta(None) == {}


def test_wait_if_paused_fails_open_and_raises_on_kill(no_api, monkeypatch):
    cs.wait_if_paused()  # API down → returns immediately
    states = iter(["paused", "paused", "healthy"])
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"agent": {"state": next(states)}}))
    cs.wait_if_paused(poll_seconds=0)  # returns once resumed
    monkeypatch.setattr(cs, "_api", lambda *a, **k: (200, {"agent": {"state": "killed"}}))
    with pytest.raises(cs.AgentKilled):
        cs.wait_if_paused(poll_seconds=0)


def test_gate_holds_big_refund_for_approval(mock_api, monkeypatch):
    monkeypatch.setattr(cs._s, "agent_id", "delta")
    monkeypatch.setattr(cs._s, "approval_timeout", 0.0)
    decision, _ = cs.gate("issue_refund", {"order_id": 1, "amount": 50000}, 410.0)
    assert decision == "timeout"                      # nobody approved in time → treated as deny
    assert cs.gate("orders_api", {"order_id": 1})[0] == "allow"
