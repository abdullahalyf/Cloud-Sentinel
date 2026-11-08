"""
The sharding contract (CONTRACTS §3, §5, §6 — added 8 Nov).

N brain worker processes share one fleet. They agree on who owns what through a
`workers` table: every worker heartbeats into it, and the owner of an agent is decided
by rendezvous hashing over the workers that are still alive.

These tests cover the contract side — the table, the store methods, the settings and the
health fields. The sharding logic itself (who owns what, the takeover) is in
`brain/tests/test_sharding.py`.
"""
from __future__ import annotations

import time

import pytest

from shared.config import load_settings
from shared.store import LocalStore


# ── the settings ───────────────────────────────────────────────────────────
def test_the_worker_settings_exist(monkeypatch):
    for name in ("CS_WORKER_ID", "CS_WORKER_HEARTBEAT_SECONDS", "CS_WORKER_STALE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    cfg = load_settings()
    assert cfg.worker_id == ""
    assert cfg.worker_heartbeat_seconds == 2.0
    assert cfg.worker_stale_seconds == 10.0


def test_the_worker_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("CS_WORKER_ID", "brain-7")
    monkeypatch.setenv("CS_WORKER_HEARTBEAT_SECONDS", "1.5")
    monkeypatch.setenv("CS_WORKER_STALE_SECONDS", "8")
    cfg = load_settings()
    assert cfg.worker_id == "brain-7"
    assert cfg.worker_heartbeat_seconds == 1.5
    assert cfg.worker_stale_seconds == 8.0


@pytest.mark.parametrize("name", ["worker_id", "worker_heartbeat_seconds", "worker_stale_seconds"])
def test_the_new_settings_have_a_default(name):
    """A missing env var must not break Settings (the dataclass has no default for it)."""
    assert hasattr(load_settings(), name)


def test_the_stale_window_is_longer_than_the_heartbeat():
    """A worker that beats every 2 s must not look dead after 2 s. If the stale window were
    shorter than the heartbeat, the workers would take over from each other forever."""
    cfg = load_settings()
    assert cfg.worker_stale_seconds > cfg.worker_heartbeat_seconds


def test_the_stale_window_fits_in_the_takeover_budget():
    """The acceptance case is a takeover within 15 s. With a 10 s stale window the survivors
    notice at the latest after 10 s — that has to leave room inside the 15 s budget."""
    cfg = load_settings()
    assert cfg.worker_stale_seconds <= 15.0


# ── the workers table ───────────────────────────────────────────────────────
@pytest.fixture
def store(tmp_path):
    s = LocalStore(str(tmp_path / "workers.db"))
    yield s
    s.reset()


def test_the_workers_table_exists(store):
    rows = store.list_workers()
    assert rows == []


def test_a_heartbeat_registers_a_worker(store):
    store.heartbeat_worker("w1", started_at=100.0, last_seen=100.0, agents_owned=3, pid=42)
    workers = store.list_workers()
    assert len(workers) == 1
    assert workers[0]["worker_id"] == "w1"
    assert workers[0]["agents_owned"] == 3
    assert workers[0]["pid"] == 42


def test_a_second_heartbeat_updates_the_worker_instead_of_duplicating_it(store):
    store.heartbeat_worker("w1", started_at=100.0, last_seen=100.0, agents_owned=3)
    store.heartbeat_worker("w1", started_at=100.0, last_seen=102.0, agents_owned=5)
    workers = store.list_workers()
    assert len(workers) == 1
    assert workers[0]["last_seen"] == 102.0
    assert workers[0]["agents_owned"] == 5


def test_the_heartbeat_does_not_move_started_at(store):
    """`started_at` is when the worker came up. If the heartbeat moved it, a worker's uptime
    would reset every two seconds and nobody could tell a fresh worker from a long-running one."""
    store.heartbeat_worker("w1", started_at=100.0, last_seen=100.0, agents_owned=1)
    store.heartbeat_worker("w1", started_at=100.0, last_seen=130.0, agents_owned=1)
    workers = store.list_workers()
    assert workers[0]["started_at"] == 100.0
    assert workers[0]["last_seen"] == 130.0


def test_several_workers_are_all_listed(store):
    for i in range(4):
        store.heartbeat_worker(f"w{i}", started_at=100.0, last_seen=100.0, agents_owned=i)
    assert {w["worker_id"] for w in store.list_workers()} == {"w0", "w1", "w2", "w3"}


def test_only_the_workers_that_beat_recently_are_live(store):
    """A worker that stopped beating is dead. Its agents must be taken over, so it must not
    appear in the live list."""
    now = time.time()
    store.heartbeat_worker("alive", started_at=now - 30, last_seen=now - 1, agents_owned=2)
    store.heartbeat_worker("dead", started_at=now - 300, last_seen=now - 120, agents_owned=4)
    live = {w["worker_id"] for w in store.list_workers(seen_within_seconds=10)}
    assert live == {"alive"}


def test_removing_a_worker_forgets_it(store):
    store.heartbeat_worker("w1", started_at=100.0, last_seen=100.0, agents_owned=1)
    store.remove_worker("w1")
    assert store.list_workers() == []


def test_removing_a_worker_that_is_not_there_is_fine(store):
    store.remove_worker("never-existed")   # must not raise


# ── the SQL schema ─────────────────────────────────────────────────────────
def test_the_sql_schema_has_the_workers_table():
    """The LocalStore and the Postgres schema must agree, or a Supabase deployment would
    not have the table the brain writes to."""
    from pathlib import Path

    schema = (Path(__file__).resolve().parents[2] / "telemetry" / "db" / "schema.sql").read_text(
        encoding="utf-8")
    assert "create table if not exists workers" in schema
    for column in ("worker_id", "started_at", "last_seen", "agents_owned", "pid"):
        assert column in schema, column
