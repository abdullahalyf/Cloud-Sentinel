"""
Storage layer. Everyone uses `get_store()` — nobody talks to Supabase/SQLite directly.

  • Supabase configured in .env  → SupabaseStore (cloud, shared by the team)
  • Not configured               → LocalStore   (SQLite file, works offline)

Both have exactly the same methods, so the rest of the code doesn't care which one it got.
Owner: Fojle (database), with Alif.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from shared.config import settings
from shared.contracts import ActionRow, AlertRow, CommandRow, MetricRow, utc_now_iso


def _since_iso(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _build_summary(kills: int, saved: int, tokens_by_agent: dict[str, int]) -> dict:
    """Same shape from both stores. Agents are sorted: the biggest token user first."""
    ordered = dict(sorted(tokens_by_agent.items(), key=lambda kv: kv[1], reverse=True))
    return {"total_kills": int(kills), "tokens_saved": int(saved), "tokens_by_agent": ordered}


class Store(Protocol):
    # writes (sentinel)
    def insert_metric(self, row: MetricRow) -> None: ...
    def insert_alert(self, row: AlertRow) -> None: ...
    def insert_action(self, row: ActionRow) -> None: ...
    # commands (dashboard writes, sentinel reads)
    def insert_command(self, row: CommandRow) -> None: ...
    def pending_commands(self) -> list[dict]: ...
    def finish_command(self, command_id: int, status: str, result: str) -> None: ...
    # reads (dashboard)
    def recent_metrics(self, minutes: float = 5) -> list[dict]: ...
    def recent_alerts(self, limit: int = 50) -> list[dict]: ...
    def recent_actions(self, limit: int = 50) -> list[dict]: ...
    def summary(self) -> dict: ...  # {"total_kills", "tokens_saved", "tokens_by_agent": {agent: tokens}}


# ─────────────────────────────────────────────────────────────────────────────
class LocalStore:
    """SQLite version. Same tables as db/schema.sql."""

    _SCHEMA = """
    create table if not exists agent_metrics (
        id integer primary key autoincrement, agent text, container_id text,
        tokens_per_min integer, calls_per_sec real, total_tokens integer, token_budget integer,
        loop_repeats integer, memory_mb real, memory_pct real, status text, created_at text);
    create table if not exists alerts (
        id integer primary key autoincrement, agent text, severity text, rule text,
        message text, created_at text);
    create table if not exists actions (
        id integer primary key autoincrement, agent text, action text, actor text,
        reason text, tokens_saved_estimate integer, created_at text);
    create table if not exists commands (
        id integer primary key autoincrement, agent text, command text, requested_by text,
        reason text, status text, result text, created_at text);
    """

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("pragma journal_mode=wal")  # sentinel + dashboard at the same time
        self._conn.executescript(self._SCHEMA)
        self._lock = threading.Lock()

    def _insert(self, table: str, row: dict) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock:
            self._conn.execute(f"insert into {table} ({cols}) values ({marks})", list(row.values()))
            self._conn.commit()

    def _select(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def insert_metric(self, row: MetricRow) -> None:
        self._insert("agent_metrics", row.to_row())

    def insert_alert(self, row: AlertRow) -> None:
        self._insert("alerts", row.to_row())

    def insert_action(self, row: ActionRow) -> None:
        self._insert("actions", row.to_row())

    def insert_command(self, row: CommandRow) -> None:
        self._insert("commands", row.to_row())

    def pending_commands(self) -> list[dict]:
        return self._select("select * from commands where status='pending' order by id")

    def finish_command(self, command_id: int, status: str, result: str) -> None:
        with self._lock:
            self._conn.execute(
                "update commands set status=?, result=? where id=?", (status, result, command_id)
            )
            self._conn.commit()

    def recent_metrics(self, minutes: float = 5) -> list[dict]:
        return self._select(
            "select * from agent_metrics where created_at >= ? order by created_at",
            (_since_iso(minutes),),
        )

    def recent_alerts(self, limit: int = 50) -> list[dict]:
        return self._select("select * from alerts order by id desc limit ?", (limit,))

    def recent_actions(self, limit: int = 50) -> list[dict]:
        return self._select("select * from actions order by id desc limit ?", (limit,))

    def summary(self) -> dict:
        kills = self._select(
            "select count(*) as n, coalesce(sum(tokens_saved_estimate), 0) as saved "
            "from actions where action = 'KILL'"
        )[0]
        rows = self._select(
            "select agent, max(total_tokens) as tokens from agent_metrics group by agent"
        )
        return _build_summary(kills["n"], kills["saved"], {r["agent"]: r["tokens"] or 0 for r in rows})


# ─────────────────────────────────────────────────────────────────────────────
class SupabaseStore:
    """Supabase (PostgreSQL in the cloud). Run db/schema.sql in Supabase first."""

    def __init__(self, url: str, key: str):
        from supabase import create_client  # imported here so offline users don't need it

        self._db = create_client(url, key)

    def _insert(self, table: str, row: dict) -> None:
        self._db.table(table).insert(row).execute()

    def _fetch_all(self, build) -> list[dict]:
        """Supabase returns at most 1000 rows per request, so read page by page."""
        rows: list[dict] = []
        start = 0
        while True:
            page = build().range(start, start + 999).execute().data or []
            rows.extend(page)
            if len(page) < 1000:
                return rows
            start += 1000

    def insert_metric(self, row: MetricRow) -> None:
        self._insert("agent_metrics", row.to_row())

    def insert_alert(self, row: AlertRow) -> None:
        self._insert("alerts", row.to_row())

    def insert_action(self, row: ActionRow) -> None:
        self._insert("actions", row.to_row())

    def insert_command(self, row: CommandRow) -> None:
        self._insert("commands", row.to_row())

    def pending_commands(self) -> list[dict]:
        res = (
            self._db.table("commands").select("*").eq("status", "pending").order("id").execute()
        )
        return res.data or []

    def finish_command(self, command_id: int, status: str, result: str) -> None:
        self._db.table("commands").update({"status": status, "result": result}).eq(
            "id", command_id
        ).execute()

    def recent_metrics(self, minutes: float = 5) -> list[dict]:
        res = (
            self._db.table("agent_metrics")
            .select("*")
            .gte("created_at", _since_iso(minutes))
            .order("created_at")
            .limit(5000)
            .execute()
        )
        return res.data or []

    def recent_alerts(self, limit: int = 50) -> list[dict]:
        res = self._db.table("alerts").select("*").order("id", desc=True).limit(limit).execute()
        return res.data or []

    def recent_actions(self, limit: int = 50) -> list[dict]:
        res = self._db.table("actions").select("*").order("id", desc=True).limit(limit).execute()
        return res.data or []

    def summary(self) -> dict:
        # kills + tokens saved: the actions table is small, read all of it
        actions = self._fetch_all(
            lambda: self._db.table("actions").select("action,tokens_saved_estimate").order("id")
        )
        kills = [a for a in actions if a["action"] == "KILL"]
        saved = sum(a["tokens_saved_estimate"] or 0 for a in kills)
        return _build_summary(len(kills), saved, self._tokens_by_agent())

    def _tokens_by_agent(self) -> dict[str, int]:
        """Highest total_tokens per agent, in ONE request (function in db/summary.sql)."""
        try:
            rows = self._db.rpc("agent_token_totals", {}).execute().data or []
            return {r["agent"]: int(r["tokens"] or 0) for r in rows}
        except Exception:  # noqa: BLE001 - summary.sql not run yet: still ONE request, newest rows only
            rows = (
                self._db.table("agent_metrics")
                .select("agent,total_tokens")
                .order("id", desc=True)
                .limit(1000)
                .execute()
                .data
                or []
            )
            best: dict[str, int] = {}
            for r in rows:
                best[r["agent"]] = max(best.get(r["agent"], 0), int(r["total_tokens"] or 0))
            return best


# ─────────────────────────────────────────────────────────────────────────────
_store: Store | None = None


def get_store() -> Store:
    """The one function everybody calls to get the database."""
    global _store
    if _store is None:
        if settings.use_supabase:
            _store = SupabaseStore(settings.supabase_url, settings.supabase_key)
        else:
            _store = LocalStore(settings.local_db_path)
    return _store


__all__ = ["Store", "LocalStore", "SupabaseStore", "get_store", "utc_now_iso"]
