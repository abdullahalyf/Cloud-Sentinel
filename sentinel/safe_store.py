"""
SafeStore: wraps the real store so a database outage can never stop the guard.

  • a failed write (metric, alert, action, finished command) is kept in a memory buffer
    and retried in order on later ticks; the oldest rows are dropped if the buffer fills
  • after a failure the database is left alone for STORE_RETRY_SECONDS (writes go
    straight to the buffer), so a hanging Supabase doesn't slow every tick
  • pending_commands() returns [] while the database is down (no dashboard commands,
    but rules and the brain keep detecting and killing)
  • a "poison" row (the database is up but this one row always fails) is dropped after
    STORE_MAX_ROW_FAILURES tries, so it can never block the buffer or the dashboard's Kill switch
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
        self.poisoned = 0         # rows dropped because they failed again and again
        self._fails: dict[int, int] = {}   # id(buffer entry) → failed tries while the database was up

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
        """Retry buffered writes, oldest first. True when the database answers (buffer may keep poison rows)."""
        if self.clock() < self.down_until:
            return False
        entries, failed, rest, up, last_exc = list(self.buffer), [], [], None, None
        for n, entry in enumerate(entries):
            try:
                getattr(self.store, entry[0])(*entry[1])
                up = True
            except Exception as exc:
                last_exc = exc
                failed.append(entry)
                if up is None:
                    up = self._reachable()
                if not up:   # the database is down: stop here, keep everything in order
                    rest = entries[n + 1:]
                    break
        # the database answered, so a row that still fails is the row's own fault
        survivors = [e for e in failed if not (up and self._poison(e))] + rest
        self.buffer.clear()
        self.buffer.extend(survivors)
        live = {id(e) for e in self.buffer}
        self._fails = {k: n for k, n in self._fails.items() if k in live}
        if failed and not up:
            self._went_down(last_exc)
            return False
        if entries and not self.buffer:
            log.warning("Database back — all buffered rows written")
        return True

    def _reachable(self) -> bool:
        """A cheap read: tells a dead database from one bad row."""
        try:
            self.store.pending_commands()
            return True
        except Exception:
            return False

    def _poison(self, entry: tuple) -> bool:
        """Count one more failure for this row; True (and logged) once it has failed too often."""
        key = id(entry)
        self._fails[key] = self._fails.get(key, 0) + 1
        if self._fails[key] < self.cfg.store_max_row_failures:
            return False
        del self._fails[key]
        self.poisoned += 1
        log.error("Dropping a database row that failed %d times: %s %r",
                  self.cfg.store_max_row_failures, entry[0], entry[1])
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
