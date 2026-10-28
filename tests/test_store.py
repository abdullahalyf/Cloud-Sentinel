"""Tests for shared/store.py (summary, table_counts, reset) and db/reset.py.

No network: Supabase is replaced by a small in-memory fake that behaves like the real one
(it never returns more than 1000 rows per request, and it can refuse deletes).
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from shared.contracts import ActionRow, AlertRow, CommandRow, MetricRow
from shared.store import LocalStore, SupabaseStore

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("agent_metrics", "alerts", "actions", "commands")


# ── a tiny fake of the Supabase client ───────────────────────────────────────
class Result:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class Query:
    def __init__(self, fake, table):
        self.fake, self.table = fake, table
        self.op, self.payload, self.want_count = "select", None, False
        self.cols, self.filters, self.order_by, self.rng, self.max_rows = None, [], None, None, None

    def select(self, cols="*", count=None):
        self.op, self.want_count = "select", count == "exact"
        self.cols = None if cols == "*" else [c.strip() for c in cols.split(",")]
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def delete(self):
        self.op = "delete"
        return self

    def gte(self, col, value):
        self.filters.append((col, value))
        return self

    def order(self, col, desc=False):
        self.order_by = (col, desc)
        return self

    def limit(self, n):
        self.max_rows = n
        return self

    def range(self, start, end):
        self.rng = (start, end)
        return self

    def execute(self):
        self.fake.requests.append(self.table)
        rows = self.fake.tables[self.table]
        if self.op == "insert":
            row = dict(self.payload, id=self.fake.next_id)
            self.fake.next_id += 1
            rows.append(row)
            return Result([row])
        hit = [r for r in rows if all(r[c] >= v for c, v in self.filters)]
        if self.op == "delete":
            if self.fake.deny_deletes:
                raise Exception("permission denied for table " + self.table)
            self.fake.tables[self.table] = [r for r in rows if r not in hit]
            return Result(hit)
        if self.order_by:
            hit.sort(key=lambda r: r[self.order_by[0]], reverse=self.order_by[1])
        total = len(hit)
        if self.rng:
            hit = hit[self.rng[0]: self.rng[1] + 1]
        hit = hit[: min(self.max_rows or 1000, 1000)]  # Supabase never returns more than 1000 rows
        if self.cols:
            hit = [{c: r[c] for c in self.cols} for r in hit]
        return Result(hit, count=total if self.want_count else None)


class Rpc:
    def __init__(self, fake, name):
        self.fake, self.name = fake, name

    def execute(self):
        self.fake.requests.append("rpc")
        if not self.fake.has_function:
            raise Exception("Could not find the function public." + self.name)
        best = {}
        for r in self.fake.tables["agent_metrics"]:
            best[r["agent"]] = max(best.get(r["agent"], 0), r["total_tokens"])
        return Result([{"agent": a, "tokens": t} for a, t in best.items()])


class FakeSupabase:
    def __init__(self, has_function=True, deny_deletes=False):
        self.tables = {t: [] for t in TABLES}
        self.requests, self.next_id = [], 1
        self.has_function, self.deny_deletes = has_function, deny_deletes

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params=None):
        return Rpc(self, name)


def make_supabase(monkeypatch, **kwargs):
    """A real SupabaseStore talking to the fake. Returns (store, fake)."""
    fake = FakeSupabase(**kwargs)
    module = types.ModuleType("supabase")
    module.create_client = lambda url, key: fake
    monkeypatch.setitem(sys.modules, "supabase", module)
    return SupabaseStore("https://fake.supabase.co", "fake-key"), fake


@pytest.fixture(params=["local", "supabase"])
def store(request, tmp_path, monkeypatch):
    """Every test that uses this runs twice: once per store. Both must give the same answers."""
    if request.param == "local":
        return LocalStore(str(tmp_path / "t.db"))
    return make_supabase(monkeypatch)[0]


# ── helpers ──────────────────────────────────────────────────────────────────
def metric(agent, total_tokens):
    return MetricRow(agent, "c1", 100, 1.0, total_tokens, 150_000, 1, 10.0, 5.0)


def seed(s):
    for tokens in (1_000, 40_000, 95_000):          # total_tokens is a growing counter
        s.insert_metric(metric("alpha", tokens))
    for tokens in (500, 82_000):
        s.insert_metric(metric("beta", tokens))
    s.insert_metric(metric("gamma", 7_000))
    s.insert_action(ActionRow("beta", "WARN", "fallback", "soft limit", 0))
    s.insert_action(ActionRow("beta", "KILL", "rules", "hard limit", 68_000))
    s.insert_action(ActionRow("alpha", "KILL", "fallback", "loop", 55_000))
    s.insert_alert(AlertRow("beta", "warning", "token_spike", "too many tokens"))
    s.insert_command(CommandRow("beta", "KILL"))


EMPTY_SUMMARY = {"total_kills": 0, "tokens_saved": 0, "tokens_by_agent": {}}


# ── summary(): the same answer from both stores ──────────────────────────────
def test_summary_of_an_empty_database(store):
    assert store.summary() == EMPTY_SUMMARY


def test_summary_counts_kills_tokens_saved_and_tokens_per_agent(store):
    seed(store)
    got = store.summary()
    assert got == {
        "total_kills": 2,
        "tokens_saved": 123_000,
        "tokens_by_agent": {"alpha": 95_000, "beta": 82_000, "gamma": 7_000},
    }
    assert list(got["tokens_by_agent"]) == ["alpha", "beta", "gamma"]  # biggest first


def test_a_warning_is_not_a_kill(store):
    store.insert_action(ActionRow("beta", "WARN", "fallback", "soft limit", 0))
    assert store.summary()["total_kills"] == 0
    assert store.summary()["tokens_saved"] == 0


# ── table_counts() and reset() ───────────────────────────────────────────────
def test_table_counts(store):
    assert store.table_counts() == {t: 0 for t in TABLES}
    seed(store)
    assert store.table_counts() == {"agent_metrics": 6, "alerts": 1, "actions": 3, "commands": 1}


def test_reset_empties_every_table(store):
    seed(store)
    store.reset()
    assert store.table_counts() == {t: 0 for t in TABLES}
    assert store.summary() == EMPTY_SUMMARY


def test_local_ids_start_at_1_again_after_reset(tmp_path):
    s = LocalStore(str(tmp_path / "t.db"))
    seed(s)
    s.reset()
    s.insert_alert(AlertRow("beta", "info", "r", "m"))
    assert s.recent_alerts()[0]["id"] == 1


def test_both_stores_have_the_same_public_methods():
    def public(cls):
        return {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}

    assert public(LocalStore) == public(SupabaseStore)


# ── Supabase specifics ───────────────────────────────────────────────────────
def test_supabase_summary_reads_every_page_and_asks_for_tokens_once(monkeypatch):
    s, fake = make_supabase(monkeypatch)
    seed(s)
    for _ in range(2_500):                          # more than 2 pages of 1000 rows
        s.insert_action(ActionRow("beta", "KILL", "rules", "x", 10))
    fake.requests.clear()
    got = s.summary()
    assert got["total_kills"] == 2 + 2_500
    assert got["tokens_saved"] == 123_000 + 25_000
    assert fake.requests.count("rpc") == 1          # ONE request for all agents, not one per agent
    assert "agent_metrics" not in fake.requests


def test_supabase_summary_still_works_if_summary_sql_was_not_run(monkeypatch):
    s, fake = make_supabase(monkeypatch, has_function=False)
    seed(s)
    fake.requests.clear()
    assert s.summary()["tokens_by_agent"] == {"alpha": 95_000, "beta": 82_000, "gamma": 7_000}
    assert fake.requests.count("agent_metrics") == 1  # fallback is also ONE request


def test_supabase_refused_delete_is_an_error_and_keeps_the_data(monkeypatch):
    s, fake = make_supabase(monkeypatch, deny_deletes=True)
    seed(s)
    with pytest.raises(Exception, match="permission denied"):
        s.reset()
    assert s.table_counts()["agent_metrics"] == 6


# ── db/reset.py (the script) ─────────────────────────────────────────────────
def load_reset_script(monkeypatch, store):
    monkeypatch.chdir(ROOT)  # the script changes directory itself, monkeypatch puts us back after
    spec = importlib.util.spec_from_file_location("reset_script", ROOT / "db" / "reset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_store", lambda: store)
    return module


def test_reset_script_with_yes_wipes_everything(monkeypatch, tmp_path):
    s = LocalStore(str(tmp_path / "t.db"))
    seed(s)
    script = load_reset_script(monkeypatch, s)
    monkeypatch.setattr(sys, "argv", ["reset.py", "--yes"])
    assert script.main() == 0
    assert s.table_counts() == {t: 0 for t in TABLES}


def test_reset_script_deletes_nothing_if_you_do_not_type_yes(monkeypatch, tmp_path, capsys):
    s = LocalStore(str(tmp_path / "t.db"))
    seed(s)
    script = load_reset_script(monkeypatch, s)
    monkeypatch.setattr(sys, "argv", ["reset.py"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert script.main() == 1
    assert "Cancelled" in capsys.readouterr().out
    assert s.table_counts()["agent_metrics"] == 6


def test_reset_script_on_an_empty_database(monkeypatch, tmp_path, capsys):
    script = load_reset_script(monkeypatch, LocalStore(str(tmp_path / "t.db")))
    monkeypatch.setattr(sys, "argv", ["reset.py", "--yes"])
    assert script.main() == 0
    assert "Already empty" in capsys.readouterr().out


def test_reset_script_explains_when_supabase_refuses_the_delete(monkeypatch, capsys):
    s, _ = make_supabase(monkeypatch, deny_deletes=True)
    seed(s)
    script = load_reset_script(monkeypatch, s)
    monkeypatch.setattr(sys, "argv", ["reset.py", "--yes"])
    assert script.main() == 1
    assert "service_role" in capsys.readouterr().out