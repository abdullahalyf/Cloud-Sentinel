"""
Batch the brain's writes: one transaction per tick, not one per row.

**Why this file exists.** The tick writes two rows per agent — a metric and an agent
row — and the store commits after each one. At 100 agents that is 200 disk syncs per
tick, and the profile said plainly where the time went: 84% of a tick was
`sqlite3.Connection.commit`. The tick took 513 ms at 100 agents against a 200 ms
budget, and none of it was thinking — it was the disk being asked to say "yes" 200
times for one tick's worth of work.

**Why it is in the brain and not in the store.** `shared/store.py` is Fojle's folder,
and the brain does not edit other people's folders. But the *brain* is the thing that
knows it is about to write 200 rows that all belong to the same tick — the store
cannot know that. So the brain keeps its writes in memory for the length of one tick
and hands them to the store's own connection in a single transaction, using the same
SQL the store would have used.

**Why it is safe.** The batch is flushed in the same tick that filled it, in the same
order, and if anything goes wrong the rows are written one at a time exactly as
before — a failure degrades to the old behaviour instead of losing data. The
transaction is opened on the store's *own* connection and under the store's *own*
lock, so the brain still respects the busy timeout and never collides with a second
worker.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from shared.contracts import _dump

log = logging.getLogger(__name__)


class WriteBatch:
    """Collects the tick's writes and flushes them in one transaction.

    Usage:

        batch = WriteBatch(store)
        batch.metric(row)
        batch.agent(row)
        ...
        batch.flush()

    A store that is not a local SQLite store (Supabase) has no connection to batch
    against, so every write goes straight through — the same behaviour as before, one
    request per row.
    """

    def __init__(self, store: Any):
        self.store = store
        self._metrics: list[Any] = []
        self._agents: list[Any] = []
        # The connection and the lock, or None when there is nothing to batch against.
        self._conn = getattr(store, "_conn", None)
        self._lock = getattr(store, "_lock", None)

    @property
    def enabled(self) -> bool:
        """True when the writes really are being held back."""
        return self._conn is not None

    @property
    def pending(self) -> int:
        return len(self._metrics) + len(self._agents)

    # ── the writes ───────────────────────────────────────────────────────────
    def metric(self, row: Any) -> None:
        """One metric row for the agent_metrics table."""
        self._metrics.append(row)

    def agent(self, row: Any) -> None:
        """One agent row for the agents table (an upsert)."""
        self._agents.append(row)

    # ── the flush ────────────────────────────────────────────────────────────
    def flush(self) -> None:
        """Write everything that was collected, in one transaction.

        If the batched write fails for any reason, the rows are written one at a time
        with the store's own methods — the old behaviour. A batch must never be a way
        to lose a metric.
        """
        metrics, agents = self._metrics, self._agents
        self._metrics, self._agents = [], []
        if not metrics and not agents:
            return

        if not self.enabled:
            self._write_one_by_one(metrics, agents)
            return

        try:
            self._write_batched(metrics, agents)
        except Exception:
            log.exception("the batched write failed — writing the rows one at a time")
            self._write_one_by_one(metrics, agents)

    # ── the two ways of writing ──────────────────────────────────────────────
    def _write_batched(self, metrics: list[Any], agents: list[Any]) -> None:
        """One transaction, one `executemany` per table."""
        metric_sql, metric_params = _metric_insert(metrics)
        agent_sql, agent_params = _agent_upsert(agents)

        def run() -> None:
            conn = self._conn
            conn.execute("begin")
            try:
                if metric_params:
                    conn.executemany(metric_sql, metric_params)
                if agent_params:
                    conn.executemany(agent_sql, agent_params)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        lock = self._lock
        if lock is None:
            run()
        else:
            with lock:
                run()

    def _write_one_by_one(self, metrics: list[Any], agents: list[Any]) -> None:
        """The fallback: the store's own methods, one row at a time."""
        for row in metrics:
            self.store.insert_metric(row)
        for row in agents:
            self.store.upsert_agent(row)


# ── the SQL, built from the contracts so it cannot drift ────────────────────
def _metric_insert(metrics: list[Any]) -> tuple[str, list[tuple]]:
    """The same SQL the store's `_insert` builds for the agent_metrics table.

    **B9: the columns are read straight off the row, not through `to_row()`.**
    `to_row()` calls `dataclasses.asdict`, which is a *deep* copy — it walks every
    field and `copy.deepcopy`s every leaf. The metric row is flat: fourteen scalars,
    nothing nested. The deep copy is therefore pure waste, and at 1000 agents it was
    the single biggest item in the tick's profile: 2,261 `asdict` calls per tick,
    44 ms of a 169 ms tick. Reading the attributes directly is 4.2x faster and
    changes nothing about what is written — the SQL and the values come from the
    same `__dataclass_fields__` list, so the columns and the values cannot drift
    apart any more than they could before.
    """
    from shared.contracts import MetricRow

    cols = list(MetricRow.__dataclass_fields__)
    marks = ", ".join("?" for _ in cols)
    sql = f"insert into agent_metrics ({', '.join(cols)}) values ({marks})"

    params = []
    for row in metrics:
        params.append(tuple(getattr(row, c) for c in cols))
    return sql, params


def _agent_upsert(agents: list[Any]) -> tuple[str, list[tuple]]:
    """The same SQL the store's `upsert_agent` builds.

    The store has one rule that has to survive the batching: an empty baseline means
    "the caller has no new baseline" (the brain writes the agent row every tick), so
    the learned baseline already in the row must survive. Writing "{}" would wipe it.

    In one batch the rows can disagree: one agent may have learned a baseline while
    another has not. A single upsert cannot express that — the update set applies to
    every row. So the batch splits the rows in two:

      * rows that carry a baseline update it, and
      * rows that do not leave it alone.

    Both go in the same transaction, so the tick still costs one commit. The second
    group keeps the stored baseline by using `coalesce(nullif(excluded.baseline, '{}'),
    agents.baseline)` — an empty baseline falls back to what is already there, and a
    real one replaces it.

    **B9: like `_metric_insert`, the columns are read straight off the row.** The
    one column that needs work is `baseline` — the row holds it as a dict (the brain
    builds it from the learned baseline) and the column stores it as JSON text, so it
    is encoded here, once, exactly as `_dump` would have.
    """
    from shared.contracts import AgentRow

    cols = list(AgentRow.__dataclass_fields__)
    marks = ", ".join("?" for _ in cols)
    update_cols = [c for c in cols if c != "agent_id"]
    updates = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    sql = (f"insert into agents ({', '.join(cols)}) values ({marks}) "
           f"on conflict(agent_id) do update set {updates}, "
           f"baseline=coalesce(nullif(excluded.baseline, '{{}}'), agents.baseline)")

    params = []
    for row in agents:
        baseline = getattr(row, "baseline")
        params.append(tuple(
            _dump(baseline) if c == "baseline" else getattr(row, c)
            for c in cols))
    return sql, params
