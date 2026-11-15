import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "db" / "migrate.py"
_spec = importlib.util.spec_from_file_location("db_migrate", _PATH)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, db):
        self.db, self._row = db, None

    def select(self, *cols):
        return self

    def insert(self, row):
        self._row = row
        return self

    def execute(self):
        if self._row is not None:
            self.db.rows.append(dict(self._row))
            self.db.inserts += 1
        return _Result(list(self.db.rows))


class FakeDB:
    def __init__(self, rows=()):
        self.rows, self.inserts = [dict(r) for r in rows], 0

    def table(self, name):
        assert name == "schema_migrations"
        return _Table(self)


KNOWN = ["0001_init", "0002_spans_detail", "0003_realtime"]


def test_versions_are_the_sql_file_names_in_order(tmp_path):
    for name in ("0002_b.sql", "0001_a.sql", "notes.txt"):
        (tmp_path / name).write_text("select 1;")
    assert migrate.versions(tmp_path) == ["0001_a", "0002_b"]


def test_the_real_folder_has_the_three_migrations():
    assert migrate.versions() == KNOWN


def test_applied_and_pending():
    db = FakeDB([{"version": "0001_init"}])
    done = migrate.applied(db)
    assert done == {"0001_init"}
    assert migrate.pending(KNOWN, done) == ["0002_spans_detail", "0003_realtime"]


def test_mark_applied_records_once():
    db = FakeDB()
    assert migrate.mark_applied(db, "0003_realtime", KNOWN) == "marked"
    assert migrate.mark_applied(db, "0003_realtime", KNOWN) == "already"
    assert [r["version"] for r in db.rows] == ["0003_realtime"] and db.inserts == 1


def test_dry_run_records_nothing():
    db = FakeDB()
    assert migrate.mark_applied(db, "0002_spans_detail", KNOWN, dry_run=True) == "would"
    assert db.inserts == 0


def test_unknown_version_is_refused():
    with pytest.raises(ValueError):
        migrate.mark_applied(FakeDB(), "9999_nope", KNOWN)


def test_realtime_migration_is_idempotent_and_lists_the_four_tables():
    sql = (migrate.MIGRATIONS / "0003_realtime.sql").read_text(encoding="utf-8")
    for table in ("actions", "alerts", "tool_calls", "agent_memory"):
        assert f"'{table}'" in sql
    assert "if not exists" in sql and "supabase_realtime" in sql


def test_print_shows_the_sql(capsys):
    assert migrate.main(["--print", "0002_spans_detail"]) == 0
    assert "add column if not exists detail" in capsys.readouterr().out