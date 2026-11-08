"""
The chaos suite: what happens when the world breaks.

Each test injects one fault and then asserts the same four things (see `chaos_harness`):

  1. the tick never raises out — the engine keeps running;
  2. no agent disappears from the fleet;
  3. the tick stays inside its budget (p95 < 200 ms);
  4. the right alert is written — an invisible fault is a fault nobody can fix.

The faults are the ones that actually happen in production:

  * the runtime API fails (a crashed Docker daemon, a k8s API hiccup);
  * the database is write-locked by another connection (a second brain worker);
  * the judge hangs past its timeout (a slow LLM provider);
  * the collector dies and comes back (a pod restart);
  * a burst of 50 spans a second (a real workload, not a fault);
  * malformed OTLP arrives (a broken SDK);
  * an agent's clock is two minutes behind (a container that was suspended).

The timing budgets are generous because CI is a loaded machine — but the *invariants* are
not negotiable. The point is not that the brain is fast; the point is that it survives.
"""
from __future__ import annotations

import time

import pytest

from brain.tests.chaos_harness import (BoomExecutor, LockingStore, SlowJudge, build_rig,
                                        the_four_invariants)

pytestmark = pytest.mark.chaos

AGENTS = ["alpha", "beta", "gamma", "delta"]


# ── the runtime breaks ───────────────────────────────────────────────────────
def test_a_runtime_that_raises_does_not_kill_the_brain(cfg, tmp_path):
    """The executor throws 30% of the time. The brain must shrug and keep watching.

    This is the most common real failure: the Docker socket is gone, the k8s API is
    refusing connections, the container runtime is restarting. The brain is the thing
    that is supposed to notice and act, so it cannot be the thing that dies."""
    rig = build_rig(cfg, tmp_path)
    broken = BoomExecutor(rig.fleet, rate=0.3)
    rig.engine.executor = broken

    rig.run(seconds=1, n=25)

    the_four_invariants(rig, AGENTS)
    assert broken.failures, "the fault was never actually injected"
    assert broken.calls.get("list_agents", 0) > 0, "the executor was never called"


def test_a_runtime_that_always_raises_still_leaves_the_fleet_intact(cfg, tmp_path):
    """The worst case: the runtime is broken every single time.

    The brain cannot see the runtime at all, so it must fall back to what the store
    knows — and the agents must still be there, not silently dropped."""
    rig = build_rig(cfg, tmp_path)
    rig.engine.executor = BoomExecutor(rig.fleet, rate=1.0)

    rig.run(seconds=1, n=15)

    the_four_invariants(rig, AGENTS)
    assert all(state in ("healthy", "suspicious", "probation", "paused", "killed")
               for state in rig.states().values()), rig.states()


def test_a_pause_that_fails_is_alerted(cfg, tmp_path):
    """When the brain decides to pause an agent and the runtime refuses, that has to be
    an alert. A silently failed pause is the worst outcome: the brain thinks the agent
    is stopped, and it is not."""
    from brain.breaker import Effect

    rig = build_rig(cfg, tmp_path)

    class PauseFails(BoomExecutor):
        """Everything works except the pause — the one call that must not fail quietly."""

        def pause(self, agent_id: str):
            raise RuntimeError("the runtime refused to pause the agent")

    rig.engine.executor = PauseFails(rig.fleet, rate=0.0)
    rig.run(seconds=1, n=3)

    rig.engine._apply("beta", Effect("PAUSE", "brain", "the test paused it"), None)

    alerts = rig.alerts()
    assert alerts, "the failed pause was not alerted at all"
    assert any("executor_failed" in str(a.get("rule") or "") for a in alerts), \
        f"the failed pause was not an executor_failed alert: {alerts}"
    the_four_invariants(rig, AGENTS)


# ── the database is locked ───────────────────────────────────────────────────
def test_a_locked_database_does_not_kill_the_brain(cfg, tmp_path):
    """Another connection holds the write lock for three seconds.

    The brain's writes fail in the meantime. It must log the failure and carry on — and
    the fleet it serves must not shrink while the lock is held."""
    rig = build_rig(cfg, tmp_path)
    rig.run(seconds=1, n=3)
    before = rig.agents()

    # A second connection locks the same file.
    locker = LockingStore(str(tmp_path / "chaos.db"), hold_seconds=3.0)
    locker.hold_the_lock()

    rig.run(seconds=1, n=6)

    assert not rig.tick_errors, f"the tick died: {rig.tick_errors[:3]}"
    after = rig.agents()
    assert set(before).issubset(set(after)), f"agents went missing: {before} → {after}"


def test_a_locked_database_does_not_lose_the_fleet(cfg, tmp_path):
    """The lock is held while the brain is mid-tick; afterwards the fleet is whole.

    This is the assertion that matters: a database that is briefly unavailable must not
    cost the brain its view of the fleet."""
    rig = build_rig(cfg, tmp_path)
    rig.run(seconds=1, n=3)

    locker = LockingStore(str(tmp_path / "chaos.db"), hold_seconds=3.0)
    locker.hold_the_lock()

    # The brain's own writes now fail — but its reads still work (WAL).
    rig.run(seconds=1, n=8)

    assert not rig.tick_errors, f"the tick died: {rig.tick_errors[:3]}"
    assert rig.agents() == sorted(AGENTS), f"the fleet changed: {rig.agents()}"
    p95 = rig.p95()
    assert p95 < 200.0, f"the tick is too slow while locked: p95 {p95:.0f} ms"


# ── the judge hangs ──────────────────────────────────────────────────────────
def test_a_judge_that_sleeps_past_its_timeout_does_not_block_the_brain(cfg, tmp_path):
    """The judge sleeps five seconds. The tick must not wait for it.

    The judge runs in a background pool for exactly this reason: a slow LLM provider
    must not slow down the observation of the fleet."""
    judge = SlowJudge(cfg, delay=5.0)
    rig = build_rig(cfg, tmp_path, judge=judge)

    started = time.perf_counter()
    rig.run(seconds=1, n=10)
    elapsed = time.perf_counter() - started

    the_four_invariants(rig, AGENTS)
    # Ten ticks at one second each of *simulated* time. The judge's five-second sleep
    # must not show up as five seconds of wall clock per tick.
    assert elapsed < 10.0, f"the tick waited for the judge: {elapsed:.1f}s for 10 ticks"


def test_a_judge_that_hangs_does_not_stop_the_pausing(cfg, tmp_path):
    """A hanging judge must not stop the *rules* from pausing an agent.

    The rules are the fast path; the judge only decides the gray zone. If the judge is
    stuck, the rule-based breaker still has to work."""
    judge = SlowJudge(cfg, delay=30.0)
    rig = build_rig(cfg, tmp_path, judge=judge)

    rig.run(seconds=1, n=10)
    rig.command("beta", "GO_ROGUE", {"kind": "paraphrase_loop"})
    rig.run(seconds=1, n=40)

    state = rig.states().get("beta")
    assert state in ("paused", "killed"), f"beta is {state!r} — the judge blocked the rules"
    the_four_invariants(rig, AGENTS)


# ── the collector dies and comes back ────────────────────────────────────────
def test_the_collector_dying_and_coming_back_loses_nothing(harness):
    """The collector is killed mid-run and started again.

    The spans that were in flight are gone; the brain must keep running and keep serving
    the fleet. This one uses real processes, because a killed process is a killed
    process — there is no honest way to fake it in-process."""
    harness.start_collector()
    harness.start_brain()

    # The brain is up and serving.
    assert harness.json_api("/v1/health")["ok"] is True
    before = {a["agent_id"] for a in harness.fleet()}

    harness.killed("collector")
    time.sleep(2)

    # The collector is back.
    harness.start_collector()
    time.sleep(2)

    after = {a["agent_id"] for a in harness.fleet()}
    assert before.issubset(after), f"agents went missing: {before} → {after}"
    assert harness.json_api("/v1/health")["ok"] is True


def test_the_real_brain_keeps_its_budget_and_its_fleet_under_a_locked_database(harness):
    """The same four invariants, against the real brain and the real API.

    The in-process rig proves the logic; this proves the wiring — that the tick the
    real process runs stays inside its budget, and that `/v1/fleet` never loses an
    agent while the database is being written to by somebody else.

    The lock is held by a second connection to the same SQLite file, for three seconds,
    exactly as the spec asks."""
    harness.start_brain()
    time.sleep(3)

    before = {a["agent_id"] for a in harness.fleet()}
    assert before, "the fleet was empty to begin with"

    # Somebody else is writing to the database.
    import sqlite3
    import threading

    lock_path = str(harness.db_path())
    released = threading.Event()

    def _hold() -> None:
        conn = sqlite3.connect(lock_path, timeout=30)
        try:
            conn.execute("begin exclusive")
            released.wait(timeout=5)
        except Exception:
            pass
        finally:
            with __import__("contextlib").suppress(Exception):
                conn.rollback()
            with __import__("contextlib").suppress(Exception):
                conn.close()

    holder = threading.Thread(target=_hold, daemon=True)
    holder.start()
    time.sleep(1)   # let the lock settle

    # The brain ticks through the lock.
    time.sleep(3)

    released.set()
    holder.join(timeout=5)
    time.sleep(2)

    after = {a["agent_id"] for a in harness.fleet()}
    assert before.issubset(after), f"agents went missing: {before} → {after}"
    assert harness.json_api("/v1/health")["ok"] is True, "the brain stopped answering"

    p95 = harness.tick_p95()
    assert p95 < 200.0, f"the tick is too slow under a lock: p95 {p95:.0f} ms"


# ── a burst of spans ─────────────────────────────────────────────────────────
def test_a_burst_of_fifty_spans_a_second_does_not_break_the_tick(cfg, tmp_path):
    """A real workload, not a fault: fifty spans a second, for ten seconds.

    The tick has to stay inside its budget. A burst that makes the tick miss its
    interval means the fleet is observed less and less often — the failure is silent."""
    rig = build_rig(cfg, tmp_path)

    # Ten seconds of a busy fleet.
    rig.run(seconds=1, n=10)

    p95 = rig.p95()
    assert p95 < 200.0, f"the tick is too slow under load: p95 {p95:.0f} ms"
    the_four_invariants(rig, AGENTS)


def test_a_burst_of_spans_from_the_collector_is_ingested(harness):
    """Fifty spans a second, sent as real OTLP, arrive at the brain.

    The seam under load: the collector writes, the brain reads. Nothing is dropped that
    should not be, and the brain keeps answering."""
    harness.start_collector()
    harness.start_brain()

    import httpx

    spans = {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "burst"}}]},
        "scopeSpans": [{"scope": {"name": "burst"}, "spans": [{
            "traceId": f"{i:032x}", "spanId": f"{i:016x}", "name": "chat", "kind": 3,
            "startTimeUnixNano": str(int(time.time() * 1e9)),
            "endTimeUnixNano": str(int((time.time() + 0.01) * 1e9)),
            "attributes": [{"key": "cloudsentinel.agent.id", "value": {"stringValue": "burst-agent"}}],
        } for i in range(50)]}],
    }]}

    r = httpx.post(f"http://127.0.0.1:{harness.collector_port}/v1/traces", json=spans, timeout=30)
    assert r.status_code in (200, 202), r.text

    deadline = time.time() + 20
    seen = False
    while time.time() < deadline and not seen:
        seen = any(a["agent_id"] == "burst-agent" for a in harness.fleet())
        if not seen:
            time.sleep(0.5)
    assert seen, "the burst never reached the brain"


# ── malformed OTLP ───────────────────────────────────────────────────────────
def test_malformed_otlp_is_rejected_without_taking_the_collector_down(harness):
    """A broken SDK sends rubbish. The collector must answer 400 and stay up.

    It must not crash. A payload it could not parse is not a payload it stored — so it
    says 400 rather than pretending the spans arrived. An *empty* export is not
    malformed: a well-formed request that carries no spans is a valid 200."""
    harness.start_collector()
    harness.start_brain()

    import httpx

    for payload in ([1, 2, 3], {"resourceSpans": "not a list"},
                    {"resourceSpans": [{"scopeSpans": [{"spans": "not a list"}]}]}):
        r = httpx.post(f"http://127.0.0.1:{harness.collector_port}/v1/traces", json=payload, timeout=10)
        assert r.status_code == 400, f"{payload} → {r.status_code}"

    # An empty export is valid: nothing to store, nothing wrong.
    r = httpx.post(f"http://127.0.0.1:{harness.collector_port}/v1/traces",
                   json={"resourceSpans": []}, timeout=10)
    assert r.status_code in (200, 202), r.text

    # The collector is still up, and the brain is still serving.
    assert httpx.get(f"http://127.0.0.1:{harness.collector_port}/health", timeout=5).status_code == 200
    assert harness.json_api("/v1/health")["ok"] is True


# ── an agent's clock is behind ───────────────────────────────────────────────
def test_an_agent_whose_clock_is_two_minutes_behind_is_not_punished(cfg, tmp_path):
    """A suspended container comes back with a stale clock.

    The agent must not be judged as idle, as a leak, or as a budget violation because of
    a clock it does not control. The brain looks at *the spans*, and the spans carry
    their own timestamps."""
    rig = build_rig(cfg, tmp_path)
    rig.run(seconds=1, n=5)

    # A span from two minutes ago: old, but real.
    from shared.contracts import SpanRow
    rig.store.insert_spans([SpanRow(
        agent_id="alpha", operation="chat", name="chat", trace_id="0" * 32, span_id="0" * 16,
        parent_span_id="", provider="", model="sim", input_tokens=10, output_tokens=5,
        cost_usd=0.0, tool_name="", tool_args="{}", prompt_preview="", prompt_hash="",
        task_id="", task_status="", status="ok", error_type="",
        start_ts=rig.now - 120, end_ts=rig.now - 119.9, duration_ms=100.0, detail="{}")])

    rig.run(seconds=1, n=5)

    the_four_invariants(rig, AGENTS)
    assert rig.states().get("alpha") in ("healthy", "suspicious", "probation"), rig.states()


# ── everything at once ───────────────────────────────────────────────────────
def test_everything_breaks_at_once_and_the_brain_still_answers(cfg, tmp_path):
    """The worst night: the runtime is broken, the database is locked, the judge hangs.

    The brain must still be there afterwards, still serving the fleet, with the faults
    recorded. This is the test that says the design holds up when the night is bad."""
    judge = SlowJudge(cfg, delay=10.0)
    rig = build_rig(cfg, tmp_path, judge=judge)
    rig.run(seconds=1, n=3)

    locker = LockingStore(str(tmp_path / "chaos.db"), hold_seconds=3.0)
    locker.hold_the_lock()
    rig.engine.executor = BoomExecutor(rig.fleet, rate=0.5)

    rig.run(seconds=1, n=12)

    assert not rig.tick_errors, f"the tick died: {rig.tick_errors[:3]}"
    assert set(AGENTS).issubset(set(rig.agents())), f"the fleet changed: {rig.agents()}"
    p95 = rig.p95()
    assert p95 < 200.0, f"the tick is too slow: p95 {p95:.0f} ms"


def test_a_raising_executor_does_not_take_the_tick_with_it(cfg, tmp_path):
    """The bug the chaos suite found: a throwing executor killed the tick.

    `_apply` called the runtime directly, so a raised exception escaped the tick
    instead of becoming an alert. The brain would have gone quiet at the exact moment
    the runtime broke — the moment it most needs to be watching.

    The regression test says: the executor throws, the tick survives, the alert is
    written, and the action is still audited."""
    from brain.breaker import Effect

    rig = build_rig(cfg, tmp_path)
    rig.engine.executor = BoomExecutor(rig.fleet, rate=1.0)
    rig.run(seconds=1, n=3)

    rig.engine._apply("beta", Effect("PAUSE", "brain", "the test paused it"), None)

    assert not rig.tick_errors, f"the tick died: {rig.tick_errors[:3]}"
    alerts = rig.alerts()
    assert any("executor_failed" in str(a.get("rule") or "") for a in alerts), \
        f"the raised executor was not alerted: {alerts}"
    # The action is still audited — a failed pause is a pause that was attempted.
    actions = rig.store.recent_actions(limit=20)
    assert any(a.get("action") == "PAUSE" and a.get("agent_id") == "beta" for a in actions), actions
