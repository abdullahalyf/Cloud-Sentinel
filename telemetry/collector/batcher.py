"""
Batching for the OTLP collector.   Owner: Fojle.

A request only puts its rows in a bounded queue and is answered at once. One background thread
takes rows out and writes them with ONE store.insert_spans() call per batch: up to BATCH_ROWS rows,
or whatever arrived within BATCH_WAIT seconds.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import weakref

log = logging.getLogger("telemetry.collector")

MAX_QUEUE_ROWS = 10000   # rows waiting for the store; when full, the collector answers 503
BATCH_ROWS = 500         # most rows in one insert_spans() call
BATCH_WAIT = 0.2         # seconds to wait for more rows before writing a smaller batch

RETRY_DELAYS = (0.2, 0.4, 0.8, 1.6, 3.2)   # seconds to wait before retry 1..5 of a failed batch

_all: "weakref.WeakSet[SpanBatcher]" = weakref.WeakSet()


class SpanBatcher:
    def __init__(self, store, max_rows: int = MAX_QUEUE_ROWS, batch_rows: int = BATCH_ROWS,
                 wait: float = BATCH_WAIT, retry_delays=RETRY_DELAYS):
        self.store = store
        self.batch_rows = batch_rows
        self.wait = wait
        self.retry_delays = tuple(retry_delays)
        self._sleep = time.sleep  # replaced in tests
        self._q: "queue.Queue" = queue.Queue(maxsize=max_rows)
        self.accepted = 0
        self.dropped = 0
        self.failed_batches = 0
        self.last_ok = True   # did the last batch reach the store?
        _all.add(self)
        threading.Thread(target=self._run, name="span-batcher", daemon=True).start()

    def put(self, rows: list) -> None:
        """Queue all the rows, or none of them: raises queue.Full when they do not fit."""
        if self._q.maxsize - self._q.qsize() < len(rows):
            self.dropped += 1
            raise queue.Full
        for r in rows:
            self._q.put_nowait(r)
        self.accepted += len(rows)

    def qsize(self) -> int:
        return self._q.qsize()

    def _take_batch(self) -> list:
        batch = [self._q.get()]
        deadline = time.monotonic() + self.wait
        while len(batch) < self.batch_rows:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                batch.append(self._q.get(timeout=left))
            except queue.Empty:
                break
        return batch

    def _write(self, batch: list) -> None:
        """Write one batch. If the store raises, retry the SAME batch with backoff, then drop it."""
        attempts = len(self.retry_delays) + 1
        for n in range(attempts):
            try:
                self.store.insert_spans(batch)
                self.last_ok = True
                log.info("stored %d spans from %s", len(batch), ", ".join(sorted({r.agent_id for r in batch})))
                return
            except Exception as exc:
                if n < len(self.retry_delays):
                    self._sleep(self.retry_delays[n])
                else:
                    self.failed_batches += 1
                    self.last_ok = False
                    log.error("dropped a batch of %d spans after %d tries: %s", len(batch), attempts, exc)

    def _run(self) -> None:
        while True:
            batch = self._take_batch()
            try:
                self._write(batch)
            except Exception:  # never crash the thread
                log.exception("unexpected error while storing a batch")
            finally:
                for _ in batch:
                    self._q.task_done()

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until the queue is empty and everything is written (tests)."""
        end = time.time() + timeout
        while self._q.unfinished_tasks and time.time() < end:
            time.sleep(0.01)
        return not self._q.unfinished_tasks


def flush(timeout: float = 5.0) -> None:
    """Flush every batcher in this process (tests)."""
    for b in list(_all):
        b.flush(timeout)
