"""
db/migrate.py - which migration files are applied to Supabase and which are still to do.   Owner: Fojle.

supabase-py talks REST, and REST cannot run create/alter table. So this script does NOT run the SQL itself:

  python telemetry/db/migrate.py                              # status: applied / PENDING for every file
  python telemetry/db/migrate.py --print 0003_realtime        # print the SQL: paste it in Supabase -> SQL Editor -> Run
  python telemetry/db/migrate.py --mark-applied 0003_realtime # then record it in schema_migrations
  (add --dry-run to --mark-applied to only show what it would record)

A "version" is the file name without .sql. Works on Supabase only (the local SQLite file needs no migrations).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]            # repo root (this file is telemetry/db/migrate.py)
MIGRATIONS = HERE / "migrations"


def versions(folder: Path = MIGRATIONS) -> list[str]:
    """Every migration file, in name order (0001_..., 0002_...)."""
    return sorted(p.stem for p in Path(folder).glob("*.sql"))


def applied(db) -> set[str]:
    rows = db.table("schema_migrations").select("version").execute().data or []
    return {r["version"] for r in rows}


def pending(all_versions: list[str], done: set[str]) -> list[str]:
    return [v for v in all_versions if v not in done]


def mark_applied(db, version: str, known: list[str], dry_run: bool = False) -> str:
    """Record a version in schema_migrations. Returns "marked", "would", or "already"."""
    if version not in known:
        raise ValueError(f"unknown migration {version!r}; known: {', '.join(known)}")
    if version in applied(db):
        return "already"
    if dry_run:
        return "would"
    db.table("schema_migrations").insert({"version": version}).execute()
    return "marked"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show / record which migrations Supabase has.")
    parser.add_argument("--status", action="store_true", help="show applied / pending (the default)")
    parser.add_argument("--print", dest="show", metavar="VERSION", help="print the SQL of one migration")
    parser.add_argument("--mark-applied", nargs="+", metavar="VERSION", help="record versions as applied")
    parser.add_argument("--dry-run", action="store_true", help="with --mark-applied: change nothing")
    args = parser.parse_args(argv)

    known = versions()
    if args.show:
        if args.show not in known:
            print(f"unknown migration {args.show!r}; known: {', '.join(known)}")
            return 2
        print((MIGRATIONS / f"{args.show}.sql").read_text(encoding="utf-8"))
        return 0

    sys.path.insert(0, str(ROOT))   # so "from shared..." works when run as: python telemetry/db/migrate.py
    from shared.store import SupabaseStore, get_store

    store = get_store()
    if not isinstance(store, SupabaseStore):
        print("Not using Supabase (SUPABASE_URL / SUPABASE_KEY are empty): nothing to migrate.")
        return 2
    db = store._db

    if args.mark_applied:
        for version in args.mark_applied:
            try:
                print(f"  {version}: {mark_applied(db, version, known, args.dry_run)}")
            except ValueError as exc:
                print(exc)
                return 2
        return 0

    done = applied(db)
    for version in known:
        print(f"  {version:<28} {'applied' if version in done else 'PENDING'}")
    todo = pending(known, done)
    if todo:
        print(f"{len(todo)} pending: run  python telemetry/db/migrate.py --print <version>  and paste the SQL in the SQL Editor")
    return 0


if __name__ == "__main__":
    sys.exit(main())