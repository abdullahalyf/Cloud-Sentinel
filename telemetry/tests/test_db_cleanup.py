import importlib.util
import sys
from pathlib import Path

import pytest

from shared.store import TABLES, LocalStore

DB = Path(__file__).resolve().parents[1] / "db"


def _sql():
    return (DB / "cleanup.sql").read_text(encoding="utf-8")


def test_cleanup_deletes_spans_older_than_a_day_by_created_at():
    sql = _sql()
    assert "function cleanup_old_spans(keep interval default interval '1 day')" in sql
    assert "delete from spans where created_at < now() - keep;" in sql
    assert "cron.schedule('cleanup-old-spans', '5 * * * *', 'select cleanup_old_spans()')" in sql


def test_the_metrics_job_is_still_there_and_both_functions_are_locked_down():
    sql = _sql()
    assert "cron.schedule('cleanup-old-metrics', '0 * * * *', 'select cleanup_old_metrics()')" in sql
    for fn in ("cleanup_old_metrics", "cleanup_old_spans"):
        assert f"revoke execute on function {fn}(interval) from public, anon, authenticated" in sql


def test_spans_has_the_created_at_column_the_cleanup_uses():
    schema = (DB / "schema.sql").read_text(encoding="utf-8")
    block = schema.split("create table if not exists spans", 1)[1].split(");", 1)[0]
    assert "created_at" in block


@pytest.fixture
def reset_mod(monkeypatch):
    monkeypatch.chdir(Path.cwd())          # reset.py does os.chdir() on import; this restores it afterwards
    spec = importlib.util.spec_from_file_location("db_reset", DB / "reset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reset_yes_wipes_a_row_in_every_table(reset_mod, monkeypatch):
    store = LocalStore(":memory:")
    for table in TABLES:
        col = "tool_name" if table == "tool_registry" else "agent_id"
        store._exec(f"insert into {table} ({col}) values (?)", ("x",))
    before = {t: reset_mod.count_rows(store, t) for t in TABLES}
    assert all(n == 1 for n in before.values()), before
    monkeypatch.setattr(reset_mod, "get_store", lambda: store)
    monkeypatch.setattr(sys, "argv", ["reset.py", "--yes"])
    assert reset_mod.main() == 0
    assert {t: reset_mod.count_rows(store, t) for t in TABLES} == {t: 0 for t in TABLES}


def test_reset_docstring_does_not_hardcode_a_table_count():
    assert "9 tables" not in (DB / "reset.py").read_text(encoding="utf-8")