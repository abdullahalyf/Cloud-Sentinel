"""
The Supabase half of the store, tested without a Supabase project.

`supabase` is not installed in the offline CI image and there is no project to
point it at, so `shared/tests/test_store_contract.py` skips the Supabase
parametrization. That leaves the Supabase methods **untested**, which is how a
method that sends the wrong column name survives: nothing catches it until
somebody sets `SUPABASE_URL` and the brain stops writing spans.

So these tests drive the methods against a **fake client** that records what
was asked of it. They are not a mock of the Supabase SDK — they are a record of
the calls the store makes, so a change in the call shape (a renamed filter, a
dropped column, an upsert where an insert belongs) fails the test.

The two properties worth protecting:

- **the audit chain is append-only.** `insert_audit` must be a plain insert.
  An upsert would let a row be rewritten, and a chain whose rows can be
  rewritten is not a chain;
- **the span columns are exactly the table's columns.** `SpanRow.to_row()`
  produces the table's columns minus the generated `id`. Sending `id` fails
  the insert; sending a column the table does not have fails it too.
"""
from __future__ import annotations

import pytest

from shared.contracts import AuditRow, SpanRow
from shared.store import SupabaseStore


class _Result:
    def __init__(self, data=None):
        self.data = data


class _Query:
    """Records the chain of calls a store method makes."""

    def __init__(self, log: list, table: str, rows: list | None = None):
        self._log = log
        self._table = table
        self._rows = rows or []
        self._filters: list[tuple[str, object]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._upsert: bool = False
        self._on_conflict: str | None = None

    # ── query building ──
    def select(self, *cols):
        self._log.append(("select", self._table, list(cols)))
        return self

    def eq(self, col, value):
        self._filters.append(("eq", col, value))
        return self

    def gt(self, col, value):
        self._filters.append(("gt", col, value))
        return self

    def gte(self, col, value):
        self._filters.append(("gte", col, value))
        return self

    def lt(self, col, value):
        self._filters.append(("lt", col, value))
        return self

    def lte(self, col, value):
        self._filters.append(("lte", col, value))
        return self

    def order(self, col, desc: bool = False):
        self._order = (col, bool(desc))
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    # ── writing ──
    def insert(self, payload):
        self._log.append(("insert", self._table, payload, self._upsert, self._on_conflict))
        return self

    def upsert(self, payload, on_conflict=None):
        self._log.append(("insert", self._table, payload, True, on_conflict))
        self._upsert = True
        self._on_conflict = on_conflict
        return self

    def update(self, payload):
        self._log.append(("update", self._table, payload))
        return self

    def delete(self):
        self._log.append(("delete", self._table, None))
        return self

    def execute(self):
        self._log.append(("execute", self._table, self._filters, self._order, self._limit))
        return _Result(self._rows)


class _Table:
    def __init__(self, log: list, name: str, rows: list | None = None):
        self._log = log
        self._name = name
        self._rows = rows or []

    def select(self, *cols):
        return _Query(self._log, self._name, self._rows).select(*cols)

    def insert(self, payload):
        return _Query(self._log, self._name, self._rows).insert(payload)

    def upsert(self, payload, on_conflict=None):
        return _Query(self._log, self._name, self._rows).upsert(payload, on_conflict=on_conflict)

    def update(self, payload):
        return _Query(self._log, self._name, self._rows).update(payload)

    def delete(self):
        return _Query(self._log, self._name, self._rows).delete()


class FakeClient:
    """The smallest thing that behaves like the Supabase client for these calls."""

    def __init__(self, rows_by_table: dict | None = None):
        self.log: list = []
        self.rows = rows_by_table or {}

    def table(self, name: str) -> _Table:
        return _Table(self.log, name, self.rows.get(name))


@pytest.fixture
def fake_store(monkeypatch):
    """A SupabaseStore whose client is a fake that records every call."""
    client = FakeClient()
    store = SupabaseStore.__new__(SupabaseStore)   # no network, no create_client
    store._db = client
    return store, client


# ── the audit chain ────────────────────────────────────────────────────────
def test_insert_audit_appends_and_never_upserts(fake_store):
    """The chain is append-only. An upsert here would let a row be rewritten."""
    store, client = fake_store
    store.insert_audit(AuditRow(seq=1, agent_id="beta", kind="decision", actor="rules",
                                action="PAUSE", reason="loop", prev_hash="g", hash="h"))
    inserts = [c for c in client.log if c[0] == "insert" and c[1] == "audit_log"]
    assert len(inserts) == 1
    _, _, payload, upserted, on_conflict = inserts[0]
    assert upserted is False, "the audit chain must never be written with an upsert"
    assert on_conflict is None


def test_insert_audit_writes_every_column_the_chain_needs(fake_store):
    store, client = fake_store
    store.insert_audit(AuditRow(seq=7, agent_id="beta", kind="human", actor="dashboard",
                                action="RESUME", reason="ok", prev_hash="p", hash="h"))
    payload = [c for c in client.log if c[0] == "insert" and c[1] == "audit_log"][0][2]
    assert payload["seq"] == 7
    assert payload["agent_id"] == "beta"
    assert payload["kind"] == "human"
    assert payload["actor"] == "dashboard"
    assert payload["action"] == "RESUME"
    assert payload["reason"] == "ok"
    assert payload["prev_hash"] == "p"
    assert payload["hash"] == "h"
    assert payload["created_at"], "the row needs a timestamp"


def test_audit_entries_reads_in_seq_order_and_after_seq(fake_store):
    """`after_seq` is how the brain reads "the entry before this one"."""
    store, client = fake_store
    store.audit_entries(limit=5, after_seq=3)
    executed = [c for c in client.log if c[0] == "execute" and c[1] == "audit_log"]
    assert executed, "audit_entries must actually run the query"
    filters, order, limit = executed[0][2], executed[0][3], executed[0][4]
    assert ("gt", "seq", 3) in filters
    assert order == ("seq", False), "the chain must come back oldest first"
    assert limit == 5


def test_audit_head_takes_the_last_entry(fake_store):
    store, client = fake_store
    store.audit_head()
    executed = [c for c in client.log if c[0] == "execute" and c[1] == "audit_log"]
    assert executed
    filters, order, limit = executed[0][2], executed[0][3], executed[0][4]
    assert order == ("seq", True), "the head is the highest seq"
    assert limit == 1


def test_audit_head_is_none_on_an_empty_chain(fake_store):
    store, client = fake_store
    client.rows["audit_log"] = []
    assert store.audit_head() is None


def test_audit_entries_returns_decoded_rows(fake_store):
    """The rows come back as dicts, with the JSON columns decoded."""
    store, client = fake_store
    client.rows["audit_log"] = [{"seq": 1, "agent_id": "beta", "kind": "decision",
                                 "actor": "rules", "action": "PAUSE", "reason": "loop",
                                 "prev_hash": "g", "hash": "h", "created_at": "2026-11-08"}]
    rows = store.audit_entries()
    assert len(rows) == 1 and rows[0]["action"] == "PAUSE"


# ── the spans ──────────────────────────────────────────────────────────────
def test_insert_spans_writes_the_table_columns_and_not_the_generated_id(fake_store):
    """
    `spans.id` is `generated always as identity`, so sending it fails.

    `SpanRow.to_row()` produces the table's columns minus `id`, which is
    exactly what the insert has to carry.
    """
    store, client = fake_store
    store.insert_spans([SpanRow("beta", "chat", "chat sim")])
    inserts = [c for c in client.log if c[0] == "insert" and c[1] == "spans"]
    assert len(inserts) == 1
    payload = inserts[0][2]
    assert isinstance(payload, list) and len(payload) == 1
    row = payload[0]
    assert "id" not in row, "the id column is generated by Postgres"
    for column in ("agent_id", "operation", "name", "trace_id", "span_id", "parent_span_id",
                   "provider", "model", "input_tokens", "output_tokens", "cost_usd",
                   "tool_name", "tool_args", "prompt_preview", "prompt_hash",
                   "task_id", "task_status", "status", "error_type",
                   "start_ts", "end_ts", "duration_ms", "detail", "created_at"):
        assert column in row, f"the spans table has a {column} column"


def test_insert_spans_sends_the_json_columns_as_text(fake_store):
    """`tool_args` and `detail` are `text` columns holding JSON — not `jsonb`."""
    store, client = fake_store
    store.insert_spans([SpanRow("beta", "execute_tool", "t", tool_args='{"x": 1}',
                                detail='{"node": "n"}')])
    row = [c for c in client.log if c[0] == "insert" and c[1] == "spans"][0][2][0]
    assert row["tool_args"] == '{"x": 1}'
    assert row["detail"] == '{"node": "n"}'


def test_insert_spans_sends_one_batch_for_the_whole_batch(fake_store):
    """The brain writes a batch every tick; one request per span would be dozens."""
    store, client = fake_store
    store.insert_spans([SpanRow("beta", "chat", f"c{i}") for i in range(7)])
    inserts = [c for c in client.log if c[0] == "insert" and c[1] == "spans"]
    assert len(inserts) == 1
    assert len(inserts[0][2]) == 7


def test_insert_spans_with_no_rows_asks_the_database_nothing(fake_store):
    """An empty batch must not become an insert of an empty list."""
    store, client = fake_store
    store.insert_spans([])
    assert not [c for c in client.log if c[0] == "insert" and c[1] == "spans"]
