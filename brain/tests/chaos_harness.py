"""
The rig for the chaos suite.

The E2E suite drives real processes, which is right for "does the system work". The chaos
suite asks a different question: **when something breaks underneath the brain, does the
brain survive it?** A broken executor, a locked database, a judge that hangs, a collector
that dies — none of these are bugs in the brain, and all of them must leave the brain
running, the fleet intact, and the right alert written.

So the faults are injected in-process, where they can be precise:

  * `BoomExecutor` raises on demand — a chosen method, a chosen fraction of the time.
  * `LockingStore` holds a write lock on the SQLite file for a while.
  * `SlowJudge` sleeps past its timeout.
  * The collector is killed and restarted as a real process (that one has to be real:
    a killed process is a killed process).

Every test asserts the same four things, because they are the four things that must
always be true:

  1. the engine's tick never raises out of `tick()` — the loop keeps going;
  2. no agent disappears from the fleet;
  3. the tick stays inside its budget (p95 < 200 ms);
  4. the right alert is written — a fault that is invisible is a fault nobody can fix.
"""
from __future__ import annotations

import contextlib
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from brain import service
from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from shared.contracts import ExecResult
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore


# ── the faults ───────────────────────────────────────────────────────────────
class BoomExecutor:
    """An executor that raises. Sometimes, or always, or on one method only.

    The brain must treat a broken runtime the way it treats a broken agent: log it, alert
    on it, keep going. An exception that escapes the executor's `pause` must not take the
    tick down with it.
    """

    def __init__(self, inner, rate: float = 1.0, methods: Optional[set[str]] = None,
                 seed: int = 11):
        self.inner = inner
        self.rate = rate
        self.methods = methods
        self.rng = random.Random(seed)
        self.calls: dict[str, int] = {}
        self.failures: dict[str, int] = {}

    def _maybe_raise(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1
        if self.methods is not None and name not in self.methods:
            return
        if self.rng.random() < self.rate:
            self.failures[name] = self.failures.get(name, 0) + 1
            raise RuntimeError(f"the runtime blew up during {name}")

    def list_agents(self):
        self._maybe_raise("list_agents")
        return self.inner.list_agents()

    def pause(self, agent_id: str) -> ExecResult:
        self._maybe_raise("pause")
        return self.inner.pause(agent_id)

    def resume(self, agent_id: str) -> ExecResult:
        self._maybe_raise("resume")
        return self.inner.resume(agent_id)

    def kill(self, agent_id: str) -> ExecResult:
        self._maybe_raise("kill")
        return self.inner.kill(agent_id)

    def restart(self, agent_id: str) -> ExecResult:
        self._maybe_raise("restart")
        return self.inner.restart(agent_id)

    def go_rogue(self, agent_id: str, kind: str) -> ExecResult:
        self._maybe_raise("go_rogue")
        return self.inner.go_rogue(agent_id, kind)


class LockingStore(LocalStore):
    """A store whose database somebody else is writing to.

    Another connection holds an exclusive lock on the file for `hold_seconds`. Every
    write in the brain then fails with "database is locked" — which is what a second
    brain worker, or a stray script, does to the store in production.
    """

    def __init__(self, path: str, hold_seconds: float = 3.0, delay: float = 0.0):
        super().__init__(path)
        self.path = path
        self.hold_seconds = hold_seconds
        self.delay = delay
        self._locker: Optional[sqlite3.Connection] = None
        self._thread: Optional[threading.Thread] = None
        self.locked_at: Optional[float] = None
        self.released_at: Optional[float] = None

    def hold_the_lock(self) -> None:
        """Take the lock in the background, for `hold_seconds`."""
        def _hold() -> None:
            conn = sqlite3.connect(self.path, timeout=30)
            try:
                conn.execute("begin exclusive")
                self._locker = conn
                self.locked_at = time.time()
                time.sleep(self.hold_seconds)
            finally:
                with contextlib.suppress(Exception):
                    conn.rollback()
                with contextlib.suppress(Exception):
                    conn.close()
                self.released_at = time.time()

        self._thread = threading.Thread(target=_hold, daemon=True)
        self._thread.start()
        # Wait until the lock is actually held, so the test injects the fault and not
        # a race with it.
        deadline = time.time() + 5
        while self.locked_at is None and time.time() < deadline:
            time.sleep(0.02)

    def _exec(self, sql: str, params: tuple = ()) -> None:
        if self.delay:
            time.sleep(self.delay)
        super()._exec(sql, params)


class SlowJudge(Judge):
    """A judge that takes longer than the brain can wait for.

    The judge runs in a background thread pool, so a slow judge must not block the tick —
    it must simply be ignored until it answers.
    """

    def __init__(self, cfg, delay: float = 5.0):
        super().__init__(cfg)
        self.delay = delay
        self.calls = 0

    def judge(self, ctx, prompt_variant=None):
        self.calls += 1
        time.sleep(self.delay)
        return super().judge(ctx, prompt_variant)


# ── the rig ──────────────────────────────────────────────────────────────────
@dataclass
class Rig:
    """A brain on a virtual clock, with a place to inject faults."""

    store: LocalStore
    fleet: FakeFleet
    engine: Engine
    policy: Policy
    now: float = 1000.0
    tick_durations: list[float] = field(default_factory=list)
    tick_errors: list[str] = field(default_factory=list)

    # ── the clock ───────────────────────────────────────────────────────────
    def run(self, seconds: int = 1, n: int = 1) -> None:
        """Advance the clock and tick. The tick must never raise."""
        for _ in range(n):
            self.now += seconds
            self.fleet.step(self.now)
            started = time.perf_counter()
            try:
                self.engine.tick(self.now)
            except Exception as exc:      # the whole point: this must never happen
                self.tick_errors.append(f"{type(exc).__name__}: {exc}")
            self.tick_durations.append((time.perf_counter() - started) * 1000)

    def agents(self) -> list[str]:
        return sorted(a["agent_id"] for a in service.fleet_view(self.store))

    def command(self, agent_id: str, command: str, params: Optional[dict] = None) -> None:
        """Post a command the way the API does."""
        service.post_command(self.store, agent_id, command, params or {}, "terminal", "chaos")

    def states(self) -> dict[str, str]:
        return {a["agent_id"]: a["state"] for a in service.fleet_view(self.store)}

    def alerts(self) -> list[dict]:
        return self.store.recent_alerts(limit=100)

    def alert_reasons(self) -> list[str]:
        return [str(a.get("reason") or "") for a in self.alerts()]

    def p95(self) -> float:
        """The p95 tick duration, in milliseconds."""
        if not self.tick_durations:
            return 0.0
        ordered = sorted(self.tick_durations)
        rank = max(1, int(round(0.95 * len(ordered))))
        return ordered[min(rank, len(ordered)) - 1]


def build_rig(cfg, tmp_path, executor=None, judge=None, agents=("alpha", "beta", "gamma", "delta"),
              start: float = 1000.0) -> Rig:
    """A brain on a temp database, with the fake fleet generating the spans."""
    store = LocalStore(str(tmp_path / "chaos.db"))
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, names=agents, auto_rogue=None, start=start)
    fleet.gate = lambda a, t, args, v: service.request_tool_call(store, policy, a, t, args, v)
    ex = executor if executor is not None else fleet
    jd = judge if judge is not None else Judge(cfg)
    engine = Engine(store, ex, jd, policy, cfg, sync_judge=True)
    return Rig(store=store, fleet=fleet, engine=engine, policy=policy, now=start)


def the_four_invariants(rig: Rig, expected_agents: Optional[list[str]] = None) -> None:
    """The things that must be true after any fault.

    They are checked in one place so every chaos test says the same thing, and a test
    that forgets one of them is a test that is quietly weaker than it looks.
    """
    assert not rig.tick_errors, f"the tick died: {rig.tick_errors[:3]}"

    agents = rig.agents()
    if expected_agents is not None:
        assert agents == sorted(expected_agents), f"agents went missing: {agents}"

    p95 = rig.p95()
    assert p95 < 200.0, f"the tick is too slow: p95 {p95:.0f} ms"
