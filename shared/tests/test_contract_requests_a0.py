"""A0 (5 Nov): Fojle's contract requests: 4 new rogue kinds, schema_migrations table, CloudWatch settings."""
import sqlite3

from shared import config
from shared.contracts import ROGUE_KINDS
from shared.store import LocalStore

NEW_KINDS = ("prompt_injection", "tool_storm", "memory_poisoning", "slow_budget_leak")


def test_new_rogue_kinds_are_added_and_old_ones_kept():
    for kind in NEW_KINDS + ("loop", "paraphrase_loop", "token_bomb", "memory_leak", "bad_tool_call"):
        assert kind in ROGUE_KINDS


def test_cloudwatch_settings_default_off(monkeypatch):
    monkeypatch.delenv("CS_EXPORT_CLOUDWATCH", raising=False)
    monkeypatch.delenv("CS_CLOUDWATCH_FILE", raising=False)
    s = config.load_settings()
    assert s.export_cloudwatch is False
    assert s.cloudwatch_file == "data/cloudwatch.jsonl"


def test_cloudwatch_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("CS_EXPORT_CLOUDWATCH", "true")
    monkeypatch.setenv("CS_CLOUDWATCH_FILE", "data/cw-test.jsonl")
    s = config.load_settings()
    assert s.export_cloudwatch is True
    assert s.cloudwatch_file == "data/cw-test.jsonl"


def _tables(path: str) -> set[str]:
    with sqlite3.connect(path) as c:
        return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}


def test_schema_migrations_table_exists(tmp_path):
    db = str(tmp_path / "new.db")
    LocalStore(db)
    assert "schema_migrations" in _tables(db)
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("pragma table_info(schema_migrations)")}
    assert {"version", "applied_at"} <= cols


def test_old_db_without_schema_migrations_still_opens(tmp_path):
    db = str(tmp_path / "old.db")
    LocalStore(db)
    with sqlite3.connect(db) as c:  # make it look like a DB from before 5 Nov
        c.execute("drop table schema_migrations")
    assert "schema_migrations" not in _tables(db)
    store = LocalStore(db)
    assert "schema_migrations" in _tables(db)
    assert store.list_agents() == []
