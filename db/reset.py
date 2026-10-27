"""
db/reset.py - wipe all demo data so the next demo starts from a clean slate.   Owner: Fojle.

Deletes every row from: agent_metrics, alerts, actions, commands.
Works with both stores (Supabase or local SQLite): whichever get_store() gives you.

  python db/reset.py          # shows the row counts, then asks you to type "yes"
  python db/reset.py --yes    # no question (for scripts)

Needs the secret / service_role key (SUPABASE_KEY in .env). The dashboard key is not allowed to delete.
Stop the sentinel first (Ctrl+C), otherwise it writes new rows right after the wipe.
Bring killed agents back with:  docker compose up -d --force-recreate
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # so "from shared..." works when run as: python db/reset.py
os.chdir(ROOT)                  # so .env and the local SQLite path resolve from the repo root

from shared.store import SupabaseStore, get_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete ALL rows from the 4 CloudSentinel tables.")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    store = get_store()
    shared = isinstance(store, SupabaseStore)
    print("Database:", "Supabase (SHARED by the whole team!)" if shared else "local SQLite file")

    counts = store.table_counts()
    for table, n in counts.items():
        print(f"  {table:<14} {n:>8} rows")
    if sum(counts.values()) == 0:
        print("Already empty. Nothing to do.")
        return 0

    if not args.yes and input('Type "yes" to delete ALL of it: ').strip().lower() != "yes":
        print("Cancelled. Nothing was deleted.")
        return 1

    try:
        store.reset()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not delete: {exc}")
        print("Reset needs the secret / service_role key in .env, not the dashboard key.")
        return 1
    print("Done. All 4 tables are empty. Start the sentinel for a clean demo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())