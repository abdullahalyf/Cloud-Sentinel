"""Both stores must behave identically. Supabase runs only with CS_TEST_SUPABASE=1 (needs .env keys)."""
import os
import time

import pytest

from shared.contracts import (ActionRow, AgentRow, AlertRow, CommandRow, MemoryConflict, MetricRow, SpanRow,
                              ToolCallRow, VerdictRow)
from shared.store import LocalStore

STORES = ["local"] + (["supabase"] if os.getenv("CS_TEST_SUPABASE") == "1" else [])


@pytest.fixture(params=STORES)
def store(request):
    if request.param == "local":
        return LocalStore(":memory:")
    from shared.config import settings
    from shared.store import SupabaseStore

    s = SupabaseStore(settings.supabase_url, settings.supabase_key)
    s.reset()
    return s


def test_agents_upsert(store):
    store.upsert_agent(AgentRow("beta", state="healthy"))
    store.upsert_agent(AgentRow("beta", state="paused", spend_usd=0.2))
    rows = store.list_agents()
    assert len(rows) == 1 and rows[0]["state"] == "paused" and store.get_agent("beta")["spend_usd"] == pytest.approx(0.2)
    assert store.get_agent("nobody") is None


def test_spans_cursor_and_recent(store):
    now = time.time()
    store.insert_spans([SpanRow("a", "chat", "chat sim", start_ts=now - i, tool_args={"x": i}) for i in range(3)])
    store.insert_spans([])
    rows = store.spans_after(0)
    assert len(rows) == 3 and rows[0]["tool_args"] == {"x": 0}
    assert store.spans_after(rows[-1]["id"]) == []
    assert len(store.recent_spans(minutes=1, agent_id="a")) == 3


def test_metrics_alerts_verdicts_actions(store):
    store.insert_metric(MetricRow("a", "healthy", tokens_per_min=10))
    store.insert_alert(AlertRow("a", "warning", "r", "m"))
    store.insert_verdict(VerdictRow("a", "fallback", "PAUSE", 0.8, "semantic_loop", "why"))
    store.insert_action(ActionRow("a", "PAUSE", "fallback", "why", 1.5))
    assert store.recent_metrics(minutes=1, agent_id="a")[0]["tokens_per_min"] == 10
    assert store.recent_alerts(1)[0]["rule"] == "r"
    assert store.recent_verdicts(1, agent_id="a")[0]["action"] == "PAUSE"
    assert store.recent_actions(1)[0]["usd_saved_estimate"] == pytest.approx(1.5)


def test_commands(store):
    cid = store.insert_command(CommandRow("a", "SET_BUDGET", {"budget_usd": 1}))
    pending = store.pending_commands()
    assert pending[0]["id"] == cid and pending[0]["params"] == {"budget_usd": 1}
    store.finish_command(cid, "done", "ok")
    assert store.pending_commands() == []


def test_memory_versions_and_conflict(store):
    m1 = store.write_memory("beta", {"k": "v1"}, "agent")
    assert m1["version"] == 1 and m1["content"] == {"k": "v1"}
    store.write_memory("beta", {"k": "fixed"}, "human", "fix")
    with pytest.raises(MemoryConflict):
        store.write_memory("beta", {"k": "v2"}, "agent", base_version=1)  # agent hasn't seen the human fix
    m3 = store.write_memory("beta", {"k": "v3"}, "agent", base_version=2)
    assert m3["version"] == 3 and [h["version"] for h in store.memory_history("beta")] == [3, 2, 1]
    assert store.get_memory("nobody") is None


def test_tool_calls(store):
    cid = store.insert_tool_call(ToolCallRow("delta", "issue_refund", {"amount": 50000}, value_usd=410))
    assert store.list_tool_calls(status="pending")[0]["args"] == {"amount": 50000}
    store.decide_tool_call(cid, "rewrite", {"amount": 500}, "human", "too big")
    call = store.get_tool_call(cid)
    assert call["decision"] == "rewrite" and call["final_args"] == {"amount": 500} and call["decided_at"]
    assert store.list_tool_calls(status="pending") == []


def test_reset(store):
    store.insert_alert(AlertRow("a", "info", "r", "m"))
    store.reset()
    assert store.recent_alerts() == []
