"""
db/reset.py - wipe all demo data so the next demo starts from a clean slate.   Owner: Fojle.

Deletes every row from all 9 tables (see shared/store.TABLES).
Works with both stores (Supabase or local SQLite): whichever get_store() gives you.

  python telemetry/db/reset.py          # shows the row counts, then asks you to type "yes"
  python telemetry/db/reset.py --yes    # no question (for scripts)

Stop the brain first (Ctrl+C), otherwise it writes new rows right after the wipe.
Bring killed agents back with:  docker compose up -d --force-recreate
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # repo root (this file is telemetry/db/reset.py)
sys.path.insert(0, str(ROOT))   # so "from shared..." works when run as: python telemetry/db/reset.py
os.chdir(ROOT)                  # so .env and the local SQLite path resolve from the repo root

from shared.store import TABLES, LocalStore, SupabaseStore, get_store  # noqa: E402


def key_column(table: str) -> str:
    return "agent_id" if table == "agents" else "id"  # agents has no numeric id


def count_rows(store, table: str) -> int:
    if isinstance(store, LocalStore):
        return store._select(f"select count(*) as n from {table}")[0]["n"]
    res = store._db.table(table).select(key_column(table), count="exact").limit(1).execute()
    return res.count or 0


def wipe(store, table: str) -> None:
    if isinstance(store, LocalStore):
        with store._lock:
            store._conn.execute(f"delete from {table}")
            try:  # start ids from 1 again
                store._conn.execute("delete from sqlite_sequence where name = ?", (table,))
            except sqlite3.OperationalError:
                pass
            store._conn.commit()
    else:
        store._db.table(table).delete().neq(key_column(table), "-1").execute()  # Supabase needs a filter


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete ALL rows from every CloudSentinel table.")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    store = get_store()
    shared = isinstance(store, SupabaseStore)
    print("Database:", "Supabase (SHARED by the whole team!)" if shared else "local SQLite file")

    counts = {t: count_rows(store, t) for t in TABLES}
    for table, n in counts.items():
        print(f"  {table:<14} {n:>8} rows")
    if sum(counts.values()) == 0:
        print("Already empty. Nothing to do.")
        return 0

    if not args.yes and input('Type "yes" to delete ALL of it: ').strip().lower() != "yes":
        print("Cancelled. Nothing was deleted.")
        return 1

    for table in TABLES:
        wipe(store, table)
        print(f"  cleared {table}")
    print("Done. Start the brain for a clean demo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())