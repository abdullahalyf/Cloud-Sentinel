"""Tests for the write methods of SupabaseStore (task F2).
No network: Supabase is replaced by a tiny in-memory fake. The store only calls .to_row() on a row,
so a small stand-in row is enough here (the real rows are tested against real Supabase in F3)."""
import sys
import types

import pytest

from shared.store import SupabaseStore


class Row:
    """Stands in for AgentRow, SpanRow, MetricRow ..."""

    def __init__(self, **columns):
        self.columns = columns

    def to_row(self):
        return dict(self.columns)


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, fake, name):
        self.fake, self.name, self.op, self.payload, self.key = fake, name, None, None, ""

    def insert(self, rows):
        self.op, self.payload = "insert", rows
        return self

    def upsert(self, row, on_conflict=""):
        self.op, self.payload, self.key = "upsert", row, on_conflict
        return self

    def execute(self):
        self.fake.requests.append((self.name, self.op))
        stored = self.fake.tables.setdefault(self.name, [])
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        out = []
        for row in rows:
            if self.op == "upsert":
                assert self.key, "upsert needs on_conflict (the primary key column)"
                match = [r for r in stored if r[self.key] == row[self.key]]
                if match:
                    match[0].update(row)
                    out.append(match[0])
                    continue
            new = dict(row) if self.op == "upsert" else dict(row, id=len(stored) + 1)
            stored.append(new)
            out.append(new)
        return Result(out)


class FakeSupabase:
    def __init__(self):
        self.tables, self.requests = {}, []

    def table(self, name):
        return Query(self, name)


@pytest.fixture
def store_and_fake(monkeypatch):
    fake = FakeSupabase()
    module = types.ModuleType("supabase")
    module.create_client = lambda url, key: fake
    monkeypatch.setitem(sys.modules, "supabase", module)
    return SupabaseStore("https://fake.supabase.co", "fake-key"), fake


def test_upsert_agent_inserts_then_updates_the_same_agent(store_and_fake):
    store, fake = store_and_fake
    store.upsert_agent(Row(agent_id="alpha", state="healthy", spend_usd=0.1))
    store.upsert_agent(Row(agent_id="alpha", state="paused", spend_usd=0.2))
    assert fake.tables["agents"] == [{"agent_id": "alpha", "state": "paused", "spend_usd": 0.2}]


def test_upsert_agent_keeps_the_other_agents(store_and_fake):
    store, fake = store_and_fake
    store.upsert_agent(Row(agent_id="alpha", state="healthy"))
    store.upsert_agent(Row(agent_id="beta", state="healthy"))
    store.upsert_agent(Row(agent_id="alpha", state="killed"))
    states = {r["agent_id"]: r["state"] for r in fake.tables["agents"]}
    assert states == {"alpha": "killed", "beta": "healthy"}


def test_insert_spans_is_one_request_for_the_whole_list(store_and_fake):
    store, fake = store_and_fake
    store.insert_spans([Row(span_id=f"s{i}", agent_id="alpha") for i in range(500)])
    assert fake.requests == [("spans", "insert")]
    assert len(fake.tables["spans"]) == 500


def test_insert_spans_with_an_empty_list_sends_nothing(store_and_fake):
    store, fake = store_and_fake
    store.insert_spans([])
    assert fake.requests == []


def test_insert_spans_keeps_json_columns_as_text(store_and_fake):
    store, fake = store_and_fake
    store.insert_spans([Row(span_id="s1", tool_args='{"order_id": 4471}', detail="{}")])
    stored = fake.tables["spans"][0]
    assert stored["tool_args"] == '{"order_id": 4471}' and stored["detail"] == "{}"


@pytest.mark.parametrize(
    "method, table",
    [("insert_metric", "agent_metrics"), ("insert_verdict", "verdicts"), ("insert_action", "actions")],
)
def test_single_row_writes_go_to_the_right_table(store_and_fake, method, table):
    store, fake = store_and_fake
    getattr(store, method)(Row(agent_id="beta", reason="x"))
    assert fake.requests == [(table, "insert")]
    assert fake.tables[table][0]["agent_id"] == "beta" and fake.tables[table][0]["reason"] == "x"