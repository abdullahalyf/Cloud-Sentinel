"""Tests for the rest of SupabaseStore (task F3): reads, memory, tool calls, reset.

No network: Supabase is replaced by a small in-memory fake that behaves like the real one
(a request never returns more than 1000 rows). The main test runs the SAME story on LocalStore and on
SupabaseStore and demands the same answers, because "both MUST behave identically" (AGENTS.md).
"""
import sys
import time
import types
from datetime import datetime, timedelta, timezone

import pytest

from shared.contracts import MemoryConflict, load_json
from shared.store import LocalStore, SupabaseStore


# ── a tiny fake of the Supabase client ───────────────────────────────────────
class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, fake, name):
        self.fake, self.name = fake, name
        self.op, self.payload, self.cols = "select", None, None
        self.filters, self.orders, self.rng, self.max_rows, self.key = [], [], None, None, ""

    def select(self, cols="*", **_):
        self.op = "select"
        return self

    def insert(self, rows):
        self.op, self.payload = "insert", rows
        return self

    def upsert(self, row, on_conflict=""):
        self.op, self.payload, self.key = "upsert", row, on_conflict
        return self

    def update(self, values):
        self.op, self.payload = "update", values
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, value):
        self.filters.append(("eq", col, value))
        return self

    def neq(self, col, value):
        self.filters.append(("neq", col, value))
        return self

    def gt(self, col, value):
        self.filters.append(("gt", col, value))
        return self

    def gte(self, col, value):
        self.filters.append(("gte", col, value))
        return self

    def order(self, col, desc=False):
        self.orders.append((col, desc))
        return self

    def limit(self, n):
        self.max_rows = n
        return self

    def range(self, start, end):
        self.rng = (start, end)
        return self

    def _match(self, row):
        ops = {"eq": lambda a, b: a == b, "neq": lambda a, b: a != b,
               "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b}
        return all(ops[kind](row[col], value) for kind, col, value in self.filters)

    def execute(self):
        self.fake.requests.append((self.name, self.op))
        stored = self.fake.tables.setdefault(self.name, [])
        if self.op == "insert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for row in rows:
                new = dict(row, id=self.fake.next_id.get(self.name, 1))   # ids count per table, like Postgres
                self.fake.next_id[self.name] = new["id"] + 1
                stored.append(new)
                out.append(dict(new))
            return Result(out)
        if self.op == "upsert":
            assert self.key, "upsert needs on_conflict"
            match = [r for r in stored if r[self.key] == self.payload[self.key]]
            if match:
                match[0].update(self.payload)
            else:
                stored.append(dict(self.payload))
            return Result([dict(self.payload)])
        hit = [r for r in stored if self._match(r)]
        if self.op == "update":
            for r in hit:
                r.update(self.payload)
            return Result([dict(r) for r in hit])
        if self.op == "delete":
            self.fake.tables[self.name] = [r for r in stored if r not in hit]
            return Result([dict(r) for r in hit])
        for col, desc in reversed(self.orders):
            hit.sort(key=lambda r: r[col], reverse=desc)
        if self.rng:
            hit = hit[self.rng[0]: self.rng[1] + 1]
        hit = hit[: min(self.max_rows or 1000, 1000)]  # Supabase never returns more than 1000 rows
        return Result([dict(r) for r in hit])


class FakeSupabase:
    def __init__(self):
        self.tables, self.requests, self.next_id = {}, [], {}

    def table(self, name):
        return Query(self, name)


def make_supabase(monkeypatch):
    """A real SupabaseStore talking to the fake. Returns (store, fake)."""
    fake = FakeSupabase()
    module = types.ModuleType("supabase")
    module.create_client = lambda url, key: fake
    monkeypatch.setitem(sys.modules, "supabase", module)
    return SupabaseStore("https://fake.supabase.co", "fake-key"), fake


class Row:
    """Stands in for SpanRow, MetricRow ...: the store only calls .to_row()."""

    def __init__(self, **columns):
        self.columns = columns

    def to_row(self):
        return dict(self.columns)


# ── the story, with the exact column names of the tables ─────────────────────
NOW = time.time()
STAMP = datetime.now(timezone.utc)


def iso(seconds_ago):
    return (STAMP - timedelta(seconds=seconds_ago)).isoformat()


def agent(agent_id, state="healthy", spend=0.1):
    return Row(agent_id=agent_id, display_name=agent_id.title(), runtime="fake", runtime_id="c-" + agent_id,
               state=state, budget_usd=1.0, spend_usd=spend, total_tokens=100, last_seen_ts=NOW,
               updated_at=iso(0))


def span(agent_id, n, seconds_ago):
    return Row(trace_id="t1", span_id=f"{agent_id}-{n}", parent_span_id="", agent_id=agent_id, operation="chat",
               name="llm", provider="anthropic", model="claude-haiku-5-5", input_tokens=10, output_tokens=5,
               cost_usd=0.001, tool_name="", tool_args='{"order_id": 4471}', prompt_preview="hi",
               prompt_hash="h", task_id="", task_status="", status="ok", error_type="",
               start_ts=NOW - seconds_ago, end_ts=NOW - seconds_ago + 1, duration_ms=1000.0,
               detail='{"node": "refund"}', created_at=iso(seconds_ago))


def metric(agent_id, seconds_ago, tokens):
    return Row(agent_id=agent_id, state="healthy", tokens_per_min=tokens, usd_per_min=0.01, calls_per_sec=1.0,
               total_tokens=tokens, spend_usd=0.1, budget_usd=1.0, exact_repeats=0, loop_score=0.1,
               tool_cycle=0, memory_mb=100.0, memory_pct=20.0, created_at=iso(seconds_ago))


def verdict(agent_id, n):
    return Row(agent_id=agent_id, source="fallback", action="PAUSE", confidence=0.7, pattern="other",
               reason=f"reason {n}", suggested_fix="", latency_ms=5.0, created_at=iso(n))


def action(agent_id, n):
    return Row(agent_id=agent_id, action="WARN", actor="rules", reason=f"warn {n}", usd_saved_estimate=0.0,
               tokens_saved_estimate=0, created_at=iso(n))


def tool_call(agent_id, tool):
    return Row(agent_id=agent_id, tool_name=tool, args='{"amount": 50000}', decision="pending", final_args="{}",
               decided_by="", reason="", value_usd=410.0, created_at=iso(1), decided_at="")


def story(store):
    """Do the same writes, then read everything back the ways the brain and the dashboard do."""
    for name in ("beta", "alpha"):
        store.upsert_agent(agent(name))
    store.upsert_agent(agent("alpha", state="paused", spend=0.5))           # an update, not a new agent
    store.insert_spans([span("alpha", 1, 30), span("beta", 1, 20), span("alpha", 2, 10), span("beta", 2, 400)])
    for i, (who, ago, tokens) in enumerate([("alpha", 100, 5), ("beta", 90, 6), ("alpha", 80, 7), ("alpha", 4000, 8)]):
        store.insert_metric(metric(who, ago, tokens + i))
    for n in range(3):
        store.insert_verdict(verdict("alpha" if n != 1 else "beta", n))
        store.insert_action(action("alpha", n))
    first = store.write_memory("alpha", {"order_4471": "cancelled"}, "agent", "first")
    second = store.write_memory("alpha", {"order_4471": "skip it"}, "human", "fix", base_version=first["version"])
    try:
        store.write_memory("alpha", {"x": 1}, "agent", "stale", base_version=first["version"])
        conflict = False
    except MemoryConflict:
        conflict = True
    call_id = store.insert_tool_call(tool_call("alpha", "issue_refund"))
    store.insert_tool_call(tool_call("beta", "orders_api"))
    store.decide_tool_call(call_id, "deny", None, "human", "too big")

    def clean(rows):  # drop the fields that depend on the clock of the moment the call was made
        return [{k: v for k, v in r.items() if k not in ("decided_at", "created_at")} for r in rows]

    return {
        "agents": store.list_agents(),
        "agent": store.get_agent("alpha"),
        "no such agent": store.get_agent("nobody"),
        "spans_after 0": store.spans_after(0),
        "spans_after 2 limit 1": store.spans_after(2, limit=1),
        "recent_spans": store.recent_spans(minutes=1),
        "recent_spans alpha": store.recent_spans(minutes=10, agent_id="alpha"),
        "recent_metrics": store.recent_metrics(minutes=10),
        "recent_metrics beta": store.recent_metrics(minutes=10, agent_id="beta"),
        "recent_verdicts": store.recent_verdicts(limit=2),
        "recent_verdicts beta": store.recent_verdicts(agent_id="beta"),
        "recent_actions": store.recent_actions(limit=2),
        "memory": clean([store.get_memory("alpha")]),
        "memory history": clean(store.memory_history("alpha", limit=5)),
        "no memory": store.get_memory("beta"),
        "second version": second["version"],
        "conflict": conflict,
        "tool call": clean([store.get_tool_call(call_id)]),
        "no such tool call": store.get_tool_call(999),
        "tool calls": clean(store.list_tool_calls()),
        "pending tool calls": clean(store.list_tool_calls(status="pending")),
        "denied tool calls": clean(store.list_tool_calls(status="deny", limit=1)),
    }


@pytest.fixture(params=["local", "supabase"])
def store(request, monkeypatch):
    if request.param == "local":
        return LocalStore(":memory:")
    return make_supabase(monkeypatch)[0]


def test_both_stores_give_the_same_answers():
    """Same story, same answers. If someone changes one store and forgets the other, this fails."""
    local = story(LocalStore(":memory:"))
    monkeypatch = pytest.MonkeyPatch()
    try:
        remote = story(make_supabase(monkeypatch)[0])
    finally:
        monkeypatch.undo()
    for key in local:
        assert remote[key] == local[key], key


def test_the_story_really_checks_something():
    """A guard against an empty story: the answers must contain real data."""
    answers = story(LocalStore(":memory:"))
    assert [a["agent_id"] for a in answers["agents"]] == ["alpha", "beta"]
    assert answers["agent"]["state"] == "paused" and answers["no such agent"] is None
    assert answers["spans_after 0"][0]["tool_args"] == {"order_id": 4471}      # JSON text decoded
    assert len(answers["recent_spans"]) == 3 and answers["recent_metrics"][0]["agent_id"] == "alpha"
    assert answers["second version"] == 2 and answers["conflict"] is True
    assert answers["denied tool calls"][0]["decision"] == "deny"


# ── things only the Supabase side can get wrong ──────────────────────────────
def test_reading_more_than_1000_rows_uses_several_pages(monkeypatch):
    s, fake = make_supabase(monkeypatch)
    s.insert_spans([Row(span_id=str(i), agent_id="alpha", start_ts=NOW, tool_args="{}", detail="{}")
                    for i in range(2500)])
    assert len(s.spans_after(0, limit=2000)) == 2000
    assert [r["id"] for r in s.spans_after(2400)] == list(range(2401, 2501))
    assert len(s.recent_spans(minutes=1)) == 2500        # no limit: all of it, over 3 requests


def test_reset_empties_all_nine_tables_even_agents_which_has_no_id(monkeypatch):
    s, fake = make_supabase(monkeypatch)
    story(s)
    s.reset()
    assert all(not fake.tables.get(t) for t in ("agents", "spans", "agent_metrics", "alerts", "verdicts",
                                                "actions", "commands", "agent_memory", "tool_calls"))


def test_json_that_is_already_an_object_is_kept(monkeypatch):
    s, fake = make_supabase(monkeypatch)
    fake.tables["spans"] = [{"id": 1, "agent_id": "a", "start_ts": NOW, "tool_args": {"k": 1}, "detail": None}]
    row = s.spans_after(0)[0]
    assert row["tool_args"] == {"k": 1}                   # a jsonb column gives an object, not text
    assert row["detail"] == load_json(None)               # None is decoded the same way LocalStore does it


def test_every_method_of_the_protocol_is_implemented(store):
    """No NotImplementedError is left in either store."""
    for name in ("list_agents", "spans_after", "recent_spans", "recent_metrics", "recent_verdicts",
                 "recent_actions", "list_tool_calls"):
        assert getattr(store, name)(*([0] if name == "spans_after" else [])) == []
    assert store.get_agent("x") is None and store.get_memory("x") is None and store.get_tool_call(1) is None
    store.reset()