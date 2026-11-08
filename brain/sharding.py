"""
Horizontal scaling: N brain worker processes share one fleet (CONTRACTS §3, §5).

Every worker heartbeats into the `workers` table. The owner of an agent is decided by
**rendezvous hashing** (highest sha1 of `agent_id + worker_id`) over the workers that are
still alive. Two properties matter, and only one of them is obvious:

  * **Exactly one owner.** Two workers must never act on the same agent, or an agent gets
    paused twice, judged twice, and every metric is counted twice.
  * **Minimal movement.** When a worker dies, only *its* agents should move. With modulo
    hashing, adding or removing a worker reshuffles almost everything — every agent would
    jump to a different worker and the fleet would thrash. Rendezvous hashing only moves the
    agents of the worker that left.

**Never use Python's `hash()`.** It is randomised per process (PYTHONHASHSEED), so two
workers would compute different owners for the same agent. That is not a subtle bug — it
means two workers each think they own everything. `sha1` is stable across processes,
machines and runs.

    from brain.sharding import Shard, owner_of

    shard = Shard(store, worker_id="brain-1")
    shard.heartbeat(now)
    mine = shard.owned_agents(["alpha", "beta", "gamma"])   # only what this worker acts on
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Iterable, Optional

log = logging.getLogger("brain.sharding")


def worker_id_from_env(explicit: str = "") -> str:
    """This worker's id: `CS_WORKER_ID`, or one made from the pid.

    The pid keeps two workers on one machine apart. The hostname is in it too, because two
    containers on one host can share a pid namespace and then share a pid.
    """
    if explicit:
        return explicit
    from shared.config import settings

    if settings.worker_id:
        return settings.worker_id
    import socket

    return f"{socket.gethostname()}-{os.getpid()}"


def _hash(agent_id: str, worker_id: str) -> str:
    """The rendezvous weight of one (agent, worker) pair.

    The separator matters: without it, ("ab", "c") and ("a", "bc") would hash the same.
    """
    return hashlib.sha1(f"{agent_id}\x00{worker_id}".encode("utf-8")).hexdigest()


def owner_of(agent_id: str, worker_ids: Iterable[str]) -> Optional[str]:
    """The worker that owns `agent_id`, or None when there is nobody to own it.

    The owner is the worker with the highest sha1(agent_id + worker_id). Highest, not lowest
    and not a modulus — the highest hash is what makes the movement minimal.
    """
    best: Optional[str] = None
    best_hash = ""
    for worker_id in worker_ids:
        h = _hash(agent_id, worker_id)
        if h > best_hash:
            best_hash, best = h, worker_id
    return best


def assign(agent_ids: Iterable[str], worker_ids: Iterable[str]) -> dict[str, str]:
    """Map every agent to the worker that owns it: {agent_id: worker_id}."""
    workers = list(worker_ids)
    if not workers:
        return {}
    return {agent_id: owner_of(agent_id, workers) for agent_id in agent_ids}


def rebalance(agent_ids: Iterable[str], old_workers: Iterable[str],
              new_workers: Iterable[str]) -> dict[str, str]:
    """Which agents move when the worker set changes from `old_workers` to `new_workers`.

    This is the property that separates rendezvous hashing from everything else: an agent
    only moves if the worker that owned it is gone. Everything else stays where it is.
    """
    old = list(old_workers)
    new = list(new_workers)
    if not new:
        return {}
    moved: dict[str, str] = {}
    for agent_id in agent_ids:
        before = owner_of(agent_id, old) if old else None
        after = owner_of(agent_id, new)
        if before != after:
            moved[agent_id] = after
    return moved


class Shard:
    """
    One brain worker's view of the fleet.

    The worker heartbeats, reads who else is alive, and works out which agents are its own.
    The heartbeat and the ownership are separate concerns on purpose: a worker must keep
    beating even if it currently owns nothing, or the others would take over agents it is
    about to get back.
    """

    def __init__(self, store, worker_id: str = "", heartbeat_seconds: float = 2.0,
                 stale_seconds: float = 10.0, clock=time.time):
        self.store = store
        self.worker_id = worker_id_from_env(worker_id)
        self.heartbeat_seconds = heartbeat_seconds
        self.stale_seconds = stale_seconds
        self.clock = clock
        self.started_at = clock()
        self.last_heartbeat = 0.0
        self._owned: set[str] = set()

    # ── the heartbeat ───────────────────────────────────────────────────────
    def heartbeat(self, now: Optional[float] = None, agents_owned: Optional[int] = None) -> None:
        """Say "I am alive", and how much of the fleet is mine."""
        now = self.clock() if now is None else now
        count = len(self._owned) if agents_owned is None else int(agents_owned)
        try:
            self.store.heartbeat_worker(self.worker_id, started_at=self.started_at,
                                        last_seen=now, agents_owned=count, pid=os.getpid())
        except Exception:
            # A heartbeat that fails must not kill the worker — the others would take over
            # its agents while it is still running them.
            log.exception("could not write the heartbeat for %s", self.worker_id)
        self.last_heartbeat = now

    def needs_heartbeat(self, now: Optional[float] = None) -> bool:
        now = self.clock() if now is None else now
        return (now - self.last_heartbeat) >= self.heartbeat_seconds

    def shutdown(self) -> None:
        """Leave cleanly, so the others do not wait out the stale window for a ghost."""
        try:
            self.store.remove_worker(self.worker_id)
        except Exception:
            log.exception("could not remove the worker %s", self.worker_id)

    # ── who is alive ────────────────────────────────────────────────────────
    def live_workers(self, now: Optional[float] = None) -> list[str]:
        """The workers that have beaten recently. A worker that stopped is dead.

        The window is deliberately generous (`CS_WORKER_STALE_SECONDS`, 10 s against a 2 s
        heartbeat): a worker that was slow for a moment must not lose its agents, because
        two workers acting on one agent is worse than one worker being slow.

        The liveness test is done here, against *this* worker's clock, not in the store.
        The store's own `time.time()` is a different clock from the one the heartbeats
        are stamped with — a worker whose clock is off, or a test that drives a virtual
        clock, would then see every peer as dead and take over the whole fleet. Two
        workers acting on one agent is the one bug that must never happen.
        """
        now = self.clock() if now is None else now
        try:
            rows = self.store.list_workers()
        except Exception:
            log.exception("could not read the workers table")
            return [self.worker_id]
        cutoff = now - self.stale_seconds
        alive = set()
        for row in rows:
            worker_id = str(row.get("worker_id") or "")
            if not worker_id:
                continue
            try:
                last_seen = float(row.get("last_seen") or 0.0)
            except (TypeError, ValueError):
                last_seen = 0.0
            if last_seen >= cutoff:
                alive.add(worker_id)
        # This worker is always alive, even if its own heartbeat failed a moment ago —
        # it is running, and it knows it.
        alive.add(self.worker_id)
        return sorted(alive)

    def all_workers(self) -> list[str]:
        """Every worker in the table, alive or not — for diagnostics."""
        try:
            rows = self.store.list_workers()
        except Exception:
            return [self.worker_id]
        return sorted({str(r.get("worker_id") or "") for r in rows if r.get("worker_id")})

    # ── what is mine ────────────────────────────────────────────────────────
    def owned_agents(self, agent_ids: Iterable[str], now: Optional[float] = None) -> set[str]:
        """The agents this worker is responsible for.

        Only these are ticked, judged and executed. Everything else is somebody else's.
        """
        live = self.live_workers(now)
        mine = {a for a in agent_ids if owner_of(a, live) == self.worker_id}
        self._owned = mine
        return mine

    @property
    def owned_count(self) -> int:
        return len(self._owned)

    def ownership(self, agent_ids: Iterable[str], now: Optional[float] = None) -> dict[str, str]:
        """Who owns what right now: {agent_id: worker_id}. For the health check and tests."""
        live = self.live_workers(now)
        return {a: owner_of(a, live) for a in agent_ids}

    def takeover_after(self, dead_worker_id: str, agent_ids: Iterable[str]) -> set[str]:
        """The agents a dead worker's death hands over.

        With rendezvous hashing this is exactly the dead worker's agents — the rest stay
        where they are. If the death moved agents that belonged to a *live* worker, the
        hashing is broken and this is where it would show.
        """
        live = self.live_workers()
        if dead_worker_id in live:
            return set()
        dead_agents = {a for a in agent_ids if owner_of(a, [dead_worker_id]) == dead_worker_id}
        return {a for a in dead_agents if owner_of(a, live) == self.worker_id}
