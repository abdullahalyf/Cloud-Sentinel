"""
Storage layer (CONTRACTS §5). Everyone except the dashboard uses `get_store()`.

  • SUPABASE_URL + SUPABASE_KEY set → SupabaseStore (cloud, shared by the team)   — Fojle
  • not set                         → LocalStore   (SQLite file, works offline)  — reference implementation

Both MUST behave identically (shared/tests/test_store_contract.py checks this).
Read methods return plain dicts; JSON columns (tool_args, params, content, args, final_args) are
decoded to Python objects.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol

from shared.config import settings
from shared.contracts import (ActionRow, AgentRow, AlertRow, CommandRow, MemoryConflict, MemoryRow,
                              MetricRow, SpanRow, ToolCallRow, VerdictRow, load_json, utc_now_iso)

TABLES = ("agents", "spans", "agent_metrics", "alerts", "verdicts", "actions", "commands",
          "agent_memory", "tool_calls")
JSON_COLUMNS = ("tool_args", "params", "content", "args", "final_args")


def _since_iso(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def decode(row: dict) -> dict:
    """Turn JSON text columns into Python objects."""
    for col in JSON_COLUMNS:
        if col in row:
            row[col] = load_json(row[col])
    return row


class Store(Protocol):
    # writes
    def upsert_agent(self, row: AgentRow) -> None: ...
    def insert_spans(self, rows: list[SpanRow]) -> None: ...
    def insert_metric(self, row: MetricRow) -> None: ...
    def insert_alert(self, row: AlertRow) -> None: ...
    def insert_verdict(self, row: VerdictRow) -> None: ...
    def insert_action(self, row: ActionRow) -> None: ...
    def insert_command(self, row: CommandRow) -> int: ...
    def finish_command(self, command_id: int, status: str, result: str) -> None: ...
    def write_memory(self, agent_id: str, content: dict, edited_by: str, reason: str = "",
                     base_version: Optional[int] = None) -> dict: ...
    def insert_tool_call(self, row: ToolCallRow) -> int: ...
    def decide_tool_call(self, call_id: int, decision: str, final_args: Optional[dict],
                         decided_by: str, reason: str) -> None: ...
    # reads
    def list_agents(self) -> list[dict]: ...
    def get_agent(self, agent_id: str) -> Optional[dict]: ...
    def spans_after(self, last_id: int, limit: int = 2000) -> list[dict]: ...
    def recent_spans(self, minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]: ...
    def recent_metrics(self, minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]: ...
    def recent_alerts(self, limit: int = 50) -> list[dict]: ...
    def recent_verdicts(self, limit: int = 20, agent_id: Optional[str] = None) -> list[dict]: ...
    def recent_actions(self, limit: int = 50) -> list[dict]: ...
    def pending_commands(self) -> list[dict]: ...
    def get_memory(self, agent_id: str) -> Optional[dict]: ...
    def memory_history(self, agent_id: str, limit: int = 10) -> list[dict]: ...
    def get_tool_call(self, call_id: int) -> Optional[dict]: ...
    def list_tool_calls(self, status: Optional[str] = None, limit: int = 50) -> list[dict]: ...
    # admin
    def reset(self) -> None: ...


def _conflicts(history: list[dict], base_version: Optional[int], edited_by: str) -> bool:
    """An agent may not overwrite a human/MCP edit it has not seen yet."""
    if edited_by != "agent" or base_version is None:
        return False
    return any(h["version"] > base_version and h["edited_by"] in ("human", "mcp") for h in history)


# ─────────────────────────────────────────────────────────────────────────────
class LocalStore:
    """SQLite version. Same tables as telemetry/db/schema.sql."""

    _SCHEMA = """
    create table if not exists agents (
        agent_id text primary key, display_name text, runtime text, runtime_id text, state text,
        budget_usd real, spend_usd real, total_tokens integer, last_seen_ts real, updated_at text);
    create table if not exists spans (
        id integer primary key autoincrement, trace_id text, span_id text, parent_span_id text,
        agent_id text, operation text, name text, provider text, model text, input_tokens integer,
        output_tokens integer, cost_usd real, tool_name text, tool_args text, prompt_preview text,
        prompt_hash text, task_id text, task_status text, status text, error_type text,
        start_ts real, end_ts real, duration_ms real, created_at text);
    create index if not exists spans_agent_ts on spans (agent_id, start_ts);
    create table if not exists agent_metrics (
        id integer primary key autoincrement, agent_id text, state text, tokens_per_min integer,
        usd_per_min real, calls_per_sec real, total_tokens integer, spend_usd real, budget_usd real,
        exact_repeats integer, loop_score real, tool_cycle integer, memory_mb real, memory_pct real,
        created_at text);
    create index if not exists metrics_created on agent_metrics (created_at);
    create table if not exists alerts (
        id integer primary key autoincrement, agent_id text, severity text, rule text, message text,
        created_at text);
    create table if not exists verdicts (
        id integer primary key autoincrement, agent_id text, source text, action text,
        confidence real, pattern text, reason text, suggested_fix text, latency_ms real, created_at text);
    create table if not exists actions (
        id integer primary key autoincrement, agent_id text, action text, actor text, reason text,
        usd_saved_estimate real, tokens_saved_estimate integer, created_at text);
    create table if not exists commands (
        id integer primary key autoincrement, agent_id text, command text, params text,
        requested_by text, reason text, status text, result text, created_at text);
    create table if not exists agent_memory (
        id integer primary key autoincrement, agent_id text, version integer, content text,
        edited_by text, reason text, created_at text);
    create table if not exists tool_calls (
        id integer primary key autoincrement, agent_id text, tool_name text, args text,
        decision text, final_args text, decided_by text, reason text, value_usd real,
        created_at text, decided_at text);
    """

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("pragma journal_mode=wal")  # brain + dashboard + collector at once
        self._conn.executescript(self._SCHEMA)
        self._lock = threading.RLock()

    # ── helpers ──
    def _insert(self, table: str, row: dict) -> int:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock:
            cur = self._conn.execute(f"insert into {table} ({cols}) values ({marks})", list(row.values()))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def _select(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [decode(dict(r)) for r in self._conn.execute(sql, params).fetchall()]

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    # ── writes ──
    def upsert_agent(self, row: AgentRow) -> None:
        d = row.to_row()
        cols = ", ".join(d)
        marks = ", ".join("?" for _ in d)
        updates = ", ".join(f"{c}=excluded.{c}" for c in d if c != "agent_id")
        self._exec(f"insert into agents ({cols}) values ({marks}) "
                   f"on conflict(agent_id) do update set {updates}", tuple(d.values()))

    def insert_spans(self, rows: list[SpanRow]) -> None:
        if not rows:
            return
        dicts = [r.to_row() for r in rows]
        cols = ", ".join(dicts[0])
        marks = ", ".join("?" for _ in dicts[0])
        with self._lock:
            self._conn.executemany(f"insert into spans ({cols}) values ({marks})",
                                   [list(d.values()) for d in dicts])
            self._conn.commit()

    def insert_metric(self, row: MetricRow) -> None:
        self._insert("agent_metrics", row.to_row())

    def insert_alert(self, row: AlertRow) -> None:
        self._insert("alerts", row.to_row())

    def insert_verdict(self, row: VerdictRow) -> None:
        self._insert("verdicts", row.to_row())

    def insert_action(self, row: ActionRow) -> None:
        self._insert("actions", row.to_row())

    def insert_command(self, row: CommandRow) -> int:
        return self._insert("commands", row.to_row())

    def finish_command(self, command_id: int, status: str, result: str) -> None:
        self._exec("update commands set status=?, result=? where id=?", (status, result, command_id))

    def write_memory(self, agent_id: str, content: dict, edited_by: str, reason: str = "",
                     base_version: Optional[int] = None) -> dict:
        with self._lock:
            history = self.memory_history(agent_id, limit=50)
            if _conflicts(history, base_version, edited_by):
                raise MemoryConflict(f"memory of {agent_id} was changed by a human; reload it first")
            version = (history[0]["version"] if history else 0) + 1
            self._insert("agent_memory", MemoryRow(agent_id, version, content, edited_by, reason).to_row())
            return self.get_memory(agent_id)  # type: ignore[return-value]

    def insert_tool_call(self, row: ToolCallRow) -> int:
        return self._insert("tool_calls", row.to_row())

    def decide_tool_call(self, call_id: int, decision: str, final_args: Optional[dict],
                         decided_by: str, reason: str) -> None:
        from shared.contracts import _dump
        self._exec("update tool_calls set decision=?, final_args=?, decided_by=?, reason=?, decided_at=? "
                   "where id=?", (decision, _dump(final_args or {}), decided_by, reason, utc_now_iso(), call_id))

    # ── reads ──
    def list_agents(self) -> list[dict]:
        return self._select("select * from agents order by agent_id")

    def get_agent(self, agent_id: str) -> Optional[dict]:
        rows = self._select("select * from agents where agent_id=?", (agent_id,))
        return rows[0] if rows else None

    def spans_after(self, last_id: int, limit: int = 2000) -> list[dict]:
        return self._select("select * from spans where id > ? order by id limit ?", (last_id, limit))

    def recent_spans(self, minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]:
        since = time.time() - minutes * 60
        if agent_id:
            return self._select("select * from spans where agent_id=? and start_ts >= ? order by start_ts",
                                (agent_id, since))
        return self._select("select * from spans where start_ts >= ? order by start_ts", (since,))

    def recent_metrics(self, minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]:
        if agent_id:
            return self._select("select * from agent_metrics where agent_id=? and created_at >= ? "
                                "order by created_at", (agent_id, _since_iso(minutes)))
        return self._select("select * from agent_metrics where created_at >= ? order by created_at",
                            (_since_iso(minutes),))

    def recent_alerts(self, limit: int = 50) -> list[dict]:
        return self._select("select * from alerts order by id desc limit ?", (limit,))

    def recent_verdicts(self, limit: int = 20, agent_id: Optional[str] = None) -> list[dict]:
        if agent_id:
            return self._select("select * from verdicts where agent_id=? order by id desc limit ?",
                                (agent_id, limit))
        return self._select("select * from verdicts order by id desc limit ?", (limit,))

    def recent_actions(self, limit: int = 50) -> list[dict]:
        return self._select("select * from actions order by id desc limit ?", (limit,))

    def pending_commands(self) -> list[dict]:
        return self._select("select * from commands where status='pending' order by id")

    def get_memory(self, agent_id: str) -> Optional[dict]:
        rows = self.memory_history(agent_id, limit=1)
        return rows[0] if rows else None

    def memory_history(self, agent_id: str, limit: int = 10) -> list[dict]:
        return self._select("select * from agent_memory where agent_id=? order by version desc limit ?",
                            (agent_id, limit))

    def get_tool_call(self, call_id: int) -> Optional[dict]:
        rows = self._select("select * from tool_calls where id=?", (call_id,))
        return rows[0] if rows else None

    def list_tool_calls(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        if status:
            return self._select("select * from tool_calls where decision=? order by id desc limit ?",
                                (status, limit))
        return self._select("select * from tool_calls order by id desc limit ?", (limit,))

    # ── admin ──
    def reset(self) -> None:
        with self._lock:
            for t in TABLES:
                self._conn.execute(f"delete from {t}")
            self._conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
class SupabaseStore:
    """
    Supabase (PostgreSQL). Run telemetry/db/schema.sql in Supabase first.   Owner: Fojle.

    TODO(Fojle): methods raising NotImplementedError are your tasks (docs/tasks/fojle.md Day 2 + 4).
    Copy the behaviour of the LocalStore method with the same name exactly.
    Until they are done, leave SUPABASE_URL empty so everyone uses LocalStore.
    """

    def __init__(self, url: str, key: str):
        from supabase import create_client  # imported here so offline users don't need it

        self._db = create_client(url, key)

    def _insert(self, table: str, row: dict) -> int:
        res = self._db.table(table).insert(row).execute()
        return int(res.data[0]["id"]) if res.data else 0

    # ── examples that already work (copy this style) ──
    def insert_alert(self, row: AlertRow) -> None:
        self._insert("alerts", row.to_row())

    def insert_command(self, row: CommandRow) -> int:
        return self._insert("commands", row.to_row())

    def pending_commands(self) -> list[dict]:
        res = self._db.table("commands").select("*").eq("status", "pending").order("id").execute()
        return [decode(r) for r in (res.data or [])]

    def finish_command(self, command_id: int, status: str, result: str) -> None:
        self._db.table("commands").update({"status": status, "result": result}).eq("id", command_id).execute()

    def recent_alerts(self, limit: int = 50) -> list[dict]:
        res = self._db.table("alerts").select("*").order("id", desc=True).limit(limit).execute()
        return res.data or []

    # ── TODO(Fojle) Day 2: writes ──
    def upsert_agent(self, row: AgentRow) -> None:
        raise NotImplementedError("Fojle Day 2")

    def insert_spans(self, rows: list[SpanRow]) -> None:
        raise NotImplementedError("Fojle Day 2")

    def insert_metric(self, row: MetricRow) -> None:
        raise NotImplementedError("Fojle Day 2")

    def insert_verdict(self, row: VerdictRow) -> None:
        raise NotImplementedError("Fojle Day 2")

    def insert_action(self, row: ActionRow) -> None:
        raise NotImplementedError("Fojle Day 2")

    # ── TODO(Fojle) Day 4: the rest ──
    def write_memory(self, agent_id: str, content: dict, edited_by: str, reason: str = "",
                     base_version: Optional[int] = None) -> dict:
        raise NotImplementedError("Fojle Day 4")

    def insert_tool_call(self, row: ToolCallRow) -> int:
        raise NotImplementedError("Fojle Day 4")

    def decide_tool_call(self, call_id: int, decision: str, final_args: Optional[dict],
                         decided_by: str, reason: str) -> None:
        raise NotImplementedError("Fojle Day 4")

    def list_agents(self) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def get_agent(self, agent_id: str) -> Optional[dict]:
        raise NotImplementedError("Fojle Day 4")

    def spans_after(self, last_id: int, limit: int = 2000) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def recent_spans(self, minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def recent_metrics(self, minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def recent_verdicts(self, limit: int = 20, agent_id: Optional[str] = None) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def recent_actions(self, limit: int = 50) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def get_memory(self, agent_id: str) -> Optional[dict]:
        raise NotImplementedError("Fojle Day 4")

    def memory_history(self, agent_id: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def get_tool_call(self, call_id: int) -> Optional[dict]:
        raise NotImplementedError("Fojle Day 4")

    def list_tool_calls(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        raise NotImplementedError("Fojle Day 4")

    def reset(self) -> None:
        raise NotImplementedError("Fojle Day 4")


# ─────────────────────────────────────────────────────────────────────────────
_store: Optional[Store] = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """One shared store per process."""
    global _store
    with _store_lock:
        if _store is None:
            _store = (SupabaseStore(settings.supabase_url, settings.supabase_key)
                      if settings.use_supabase else LocalStore(settings.local_db_path))
        return _store
