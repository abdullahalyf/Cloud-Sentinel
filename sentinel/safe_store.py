"""
SafeStore: wraps the real store so a database outage can never stop the guard.

  • a failed write (metric, alert, action, finished command) is kept in a memory buffer
    and retried in order on later ticks; the oldest rows are dropped if the buffer fills
  • after a failure the database is left alone for STORE_RETRY_SECONDS (writes go
    straight to the buffer), so a hanging Supabase doesn't slow every tick
  • pending_commands() returns [] while the database is down (no dashboard commands,
    but rules and the brain keep detecting and killing)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Callable

from shared.config import Settings
from shared.store import Store

log = logging.getLogger("sentinel.store")


class SafeStore:
    def __init__(self, store: Store, cfg: Settings, clock: Callable[[], float] = time.time):
        self.store, self.cfg, self.clock = store, cfg, clock
        self.buffer: deque[tuple[str, tuple]] = deque(maxlen=cfg.store_buffer_size)
        self.down_until = 0.0     # don't touch the database before this time
        self.dropped = 0          # rows lost because the buffer was full

    # ── writes: never raise ──────────────────────────────────────────────────
    def insert_metric(self, row) -> None:
        self._write("insert_metric", row)

    def insert_alert(self, row) -> None:
        self._write("insert_alert", row)

    def insert_action(self, row) -> None:
        self._write("insert_action", row)

    def finish_command(self, command_id: int, status: str, result: str) -> None:
        self._write("finish_command", command_id, status, result)

    # ── reads ────────────────────────────────────────────────────────────────
    def pending_commands(self) -> list[dict]:
        if not self.flush():
            return []
        try:
            return self.store.pending_commands()
        except Exception as exc:
            self._went_down(exc)
            return []

    def __getattr__(self, name: str) -> Any:
        if name == "store":
            raise AttributeError(name)
        return getattr(self.store, name)   # dashboard-style reads pass straight through

    # ── buffer ───────────────────────────────────────────────────────────────
    @property
    def is_down(self) -> bool:
        return bool(self.buffer) or self.clock() < self.down_until

    def flush(self) -> bool:
        """Retry buffered writes, oldest first. True when the buffer is empty (DB reachable)."""
        if self.clock() < self.down_until:
            return False
        while self.buffer:
            method, args = self.buffer[0]
            try:
                getattr(self.store, method)(*args)
            except Exception as exc:
                self._went_down(exc)
                return False
            self.buffer.popleft()
            if not self.buffer:
                log.warning("Database back — all buffered rows written")
        return True

    def _write(self, method: str, *args) -> None:
        if self.flush():
            try:
                getattr(self.store, method)(*args)
                return
            except Exception as exc:
                self._went_down(exc)
        if len(self.buffer) == self.buffer.maxlen:
            self.dropped += 1
        self.buffer.append((method, args))

    def _went_down(self, exc: Exception) -> None:
        if self.clock() >= self.down_until:
            log.error("Database error (%s) — buffering writes, retry in %.0fs (%d buffered)",
                      exc, self.cfg.store_retry_seconds, len(self.buffer))
        self.down_until = self.clock() + self.cfg.store_retry_seconds
