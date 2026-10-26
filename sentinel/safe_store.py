"""
SafeStore: wraps the real store so a database outage can never stop the guard.

  • a failed write (metric, alert, action, finished command) is kept in a memory buffer
    and retried in order on later ticks; the oldest rows are dropped if the buffer fills
  • after a failure the database is left alone for STORE_RETRY_SECONDS, doubling while it keeps failing
    (max 4×): at most ONE failing call per backoff, so a read-only database never slows a tick down
  • a retry stops at the first row that fails while no write has worked since it was buffered: the write
    path is broken, not the row. Reads are tried on their own, so the Kill switch works in read-only mode
  • a "poison" row (writes work, but this one row always fails) is dropped after
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

MAX_BACKOFF_STEPS = 4    # the retry wait doubles up to 4× STORE_RETRY_SECONDS
FAILS_PER_FLUSH = 2      # a retry gives up after this many failing rows in a row, when no row worked


class SafeStore:
    def __init__(self, store: Store, cfg: Settings, clock: Callable[[], float] = time.time):
        self.store, self.cfg, self.clock = store, cfg, clock
        self.buffer: deque[tuple[str, tuple]] = deque(maxlen=cfg.store_buffer_size)
        self.down_until = 0.0     # don't write before this time
        self.read_down_until = 0.0   # don't read commands before this time
        self.dropped = 0          # rows lost because the buffer was full
        self.poisoned = 0         # rows dropped because they failed again and again
        self._streak = 0          # failed retries in a row (sets how long to wait)
        self._writes_ok = 0       # successful writes so far
        self._born: dict[int, int] = {}    # id(buffer entry) → _writes_ok when it was buffered
        self._fails: dict[int, int] = {}   # id(buffer entry) → failed tries while writes were working

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
        self.flush()
        if self.clock() < self.read_down_until:
            return []
        try:
            return self.store.pending_commands()
        except Exception as exc:
            if self.clock() >= self.read_down_until:
                log.error("Database read error (%s) — no dashboard commands, retry in %.0fs",
                          exc, self.cfg.store_retry_seconds)
            self.read_down_until = self.clock() + self.cfg.store_retry_seconds
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
        """Retry buffered writes, oldest first. True when writing may go on (inside a backoff or after a
        failed retry it is False: new rows then go straight to the buffer, no call is made)."""
        if self.clock() < self.down_until:
            return False
        entries, failed, rest, stopped, last_exc, ok = list(self.buffer), [], [], False, None, 0
        for n, entry in enumerate(entries):
            try:
                getattr(self.store, entry[0])(*entry[1])
                self._writes_ok, ok = self._writes_ok + 1, ok + 1
                continue
            except Exception as exc:
                last_exc = exc
            failed.append(entry)
            if ok == 0 and len(failed) >= FAILS_PER_FLUSH:
                # two rows in a row failed and none worked: probe with the newest row. If that works, the two
                # are poison rows and the retry goes on; if not, the write path is down — back off
                newest = entries[-1]
                if n + 1 < len(entries) and self._try(newest):
                    ok = 1
                    entries = entries[:-1]
                else:
                    rest, stopped = entries[n + 1:], True
                    break
        survivors = self._drop_poison(failed) + rest
        self.buffer.clear()
        self.buffer.extend(survivors)
        live = {id(e) for e in self.buffer}
        self._born = {k: v for k, v in self._born.items() if k in live}
        self._fails = {k: v for k, v in self._fails.items() if k in live}
        if stopped:
            self._went_down(last_exc)
            return False
        self._streak = 0
        if entries and not self.buffer:
            log.warning("Database back — all buffered rows written")
        return True

    def _try(self, entry: tuple) -> bool:
        try:
            getattr(self.store, entry[0])(*entry[1])
        except Exception:
            return False
        self._writes_ok += 1
        return True

    def _drop_poison(self, failed: list[tuple]) -> list[tuple]:
        """Rows that failed although writes worked since they were buffered (and the database answers) are
        bad rows: count the try, drop the row once it has failed too often. Others are kept untouched."""
        proved = [e for e in failed if self._writes_ok > self._born.get(id(e), self._writes_ok)]
        if not proved or not self._reachable():
            return failed
        return [e for e in failed if e not in proved or not self._poison(e)]

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
                self._writes_ok += 1
                return
            except Exception as exc:
                self._went_down(exc)
        if len(self.buffer) == self.buffer.maxlen:
            self.dropped += 1
        entry = (method, args)
        self.buffer.append(entry)
        self._born[id(entry)] = self._writes_ok

    def _went_down(self, exc: Exception | None) -> None:
        if self.clock() >= self.down_until:
            log.error("Database error (%s) — buffering writes, retry in %.0fs (%d buffered)",
                      exc, self._wait(), len(self.buffer))
        self.down_until = self.clock() + self._wait()
        self._streak += 1

    def _wait(self) -> float:
        """Seconds to leave the database alone: STORE_RETRY_SECONDS, doubling per failed retry in a row (max 4×)."""
        return self.cfg.store_retry_seconds * min(2 ** self._streak, MAX_BACKOFF_STEPS)
