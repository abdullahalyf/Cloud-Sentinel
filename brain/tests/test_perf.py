"""
A11 — the engine at 100 agents.

Two kinds of test live here:

  * **Agreement tests.** The fast paths (the batched write, the incremental loop score)
    must produce the *same* answer as the plain ones. A faster number that is a
    different number is worse than the slow number, so these check equality, not speed.

  * **The timing budget.** The tick at 100 agents has to fit inside the tick interval,
    or the brain falls behind and the fleet is observed less and less often. That test
    is marked `perf` so the nightly workflow runs it on its own schedule, and it is a
    wall-clock measurement, so it can be slowed down by a busy machine rather than by a
    slow tick.
"""
from __future__ import annotations

import time
from dataclasses import replace

import pytest

from brain import loops
from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from brain.state import AgentWindow
from brain.write_batch import WriteBatch
from shared.config import settings
from shared.contracts import AgentRow, MetricRow
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore


# ── the incremental loop score must agree with the plain one ────────────────
PARAPHRASE = [
    "look up order 4471 status",
    "check order 4471 status please",
    "get order 4471 current status",
    "retrieve order 4471 shipment status",
    "pull order 4471 delivery status",
    "query order 4471 status again",
    "lookup order 4471 status now",
]

HEALTHY = [
    "refund ticket 8832 for the duplicate charge",
    "check the weather in Dhaka tomorrow",
    "summarize the quarterly revenue report",
    "book a meeting room for Thursday",
    "translate the invoice into Bangla",
    "list the open support tickets",
    "update the shipping address for order 9911",
]


def _plain(prompts: list[str]) -> float:
    return loops.semantic_loop_score(prompts)


@pytest.mark.parametrize("prompts", [PARAPHRASE, HEALTHY, PARAPHRASE[:3], []])
def test_the_incremental_score_starts_out_the_same(prompts: list[str]):
    assert loops.IncrementalLoopScore().score(prompts) == _plain(prompts)


def test_the_incremental_score_agrees_as_the_window_slides():
    """The window slides by one prompt at a time — the case the fast path exists for."""
    incremental = loops.IncrementalLoopScore()
    window: list[str] = []
    for prompt in HEALTHY + PARAPHRASE:
        window.append(prompt)
        assert incremental.score(window) == _plain(window), f"they disagree on {window[-1]!r}"


def test_the_incremental_score_agrees_when_the_window_shrinks():
    """A prompt leaves the window: the fast path cannot model that, so it recomputes."""
    incremental = loops.IncrementalLoopScore()
    for size in range(len(HEALTHY + PARAPHRASE), 2, -1):
        window = (HEALTHY + PARAPHRASE)[:size]
        assert incremental.score(window) == _plain(window)


def test_the_incremental_score_agrees_after_a_reset():
    """A window that changed in the middle: the fast path must fall back, not guess."""
    incremental = loops.IncrementalLoopScore()
    incremental.score(HEALTHY)
    changed = HEALTHY[:-1] + ["something completely different now"]
    assert incremental.score(changed) == _plain(changed)


def test_the_incremental_score_finds_a_loop():
    """The point of the whole thing: it still catches the loop."""
    incremental = loops.IncrementalLoopScore()
    for prompt in PARAPHRASE:
        incremental.score(HEALTHY[:3] + [prompt] * 4)
    assert incremental.score(PARAPHRASE) >= 0.7


# ── the batched write must write the same rows ──────────────────────────────
def _a_metric(agent_id: str) -> MetricRow:
    return MetricRow(agent_id, "healthy", tokens_per_min=100, usd_per_min=0.5, calls_per_sec=2.0,
                     total_tokens=1000, spend_usd=1.25, budget_usd=5.0, exact_repeats=1,
                     loop_score=0.1, tool_cycle=0, memory_mb=100.0, memory_pct=20.0)


def _an_agent(agent_id: str, baseline: str = "{}") -> AgentRow:
    return AgentRow(agent_id, agent_id, "fake", "", "healthy", budget_usd=5.0, spend_usd=1.25,
                     total_tokens=1000, last_seen_ts=1000.0, baseline=baseline)


def test_the_batched_write_writes_the_same_rows(tmp_path):
    """The batch must be indistinguishable from the store's own one-at-a-time writes."""
    plain_store = LocalStore(str(tmp_path / "plain.db"))
    batch_store = LocalStore(str(tmp_path / "batch.db"))

    rows = [(_a_metric(f"a{i}"), _an_agent(f"a{i}")) for i in range(5)]
    for metric, agent in rows:
        plain_store.insert_metric(metric)
        plain_store.upsert_agent(agent)

    batch = WriteBatch(batch_store)
    for metric, agent in rows:
        batch.metric(metric)
        batch.agent(agent)
    batch.flush()

    assert batch_store.list_agents() == plain_store.list_agents()
    assert batch_store.recent_metrics() == plain_store.recent_metrics()


def test_the_batched_write_keeps_a_stored_baseline(tmp_path):
    """The store's rule: an empty baseline means "no new baseline", so the stored one
    must survive. A batch must not be a way to wipe what the brain learned."""
    store = LocalStore(str(tmp_path / "b.db"))
    store.upsert_agent(_an_agent("a1", baseline='{"tokens_per_min": 42}'))

    batch = WriteBatch(store)
    batch.agent(_an_agent("a1", baseline="{}"))
    batch.flush()

    assert store.list_agents()[0]["baseline"] == {"tokens_per_min": 42}


def test_the_batched_write_keeps_a_baseline_when_another_row_has_one(tmp_path):
    """Two agents in one batch, one with a baseline and one without: the one without
    must not lose the baseline it already had."""
    store = LocalStore(str(tmp_path / "b.db"))
    store.upsert_agent(_an_agent("a1", baseline='{"tokens_per_min": 42}'))
    store.upsert_agent(_an_agent("a2", baseline='{"tokens_per_min": 7}'))

    batch = WriteBatch(store)
    batch.agent(_an_agent("a1", baseline='{"tokens_per_min": 99}'))   # has a new one
    batch.agent(_an_agent("a2", baseline="{}"))                       # has none
    batch.flush()

    by_id = {row["agent_id"]: row["baseline"] for row in store.list_agents()}
    assert by_id["a1"] == {"tokens_per_min": 99}
    assert by_id["a2"] == {"tokens_per_min": 7}


def test_a_failed_batch_still_writes_the_rows(tmp_path):
    """A batch must never be a way to lose a metric: if it fails, the rows are written
    one at a time, exactly as before."""
    store = LocalStore(str(tmp_path / "b.db"))

    class Broken(WriteBatch):
        def _write_batched(self, metrics, agents):
            raise RuntimeError("the disk said no")

    batch = Broken(store)
    batch.metric(_a_metric("a1"))
    batch.agent(_an_agent("a1"))
    batch.flush()      # must not raise

    assert store.list_agents()[0]["agent_id"] == "a1"
    assert store.recent_metrics()


# ── the timing budget ───────────────────────────────────────────────────────
def _a_fleet_of_100(store, cfg, now: float) -> Engine:
    policy = Policy.load("brain/policies.yaml")
    names = tuple(f"agent-{i:03d}" for i in range(100))
    fleet = FakeFleet(store, names=names, auto_rogue=None, start=now)
    return Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)


@pytest.mark.perf
def test_the_tick_is_fast_at_one_hundred_agents(tmp_path):
    """The acceptance case: tick p95 < 200 ms at 100 agents.

    This is a wall-clock measurement, so it can be slowed down by a busy machine rather
    than by a slow tick. When it fails, run it on its own before believing it: the
    number to compare against is the p95 in the research notes (docs/research/
    brain-perf.md), not the number on a loaded CI box.
    """
    cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")
    store = LocalStore(str(tmp_path / "perf.db"))
    now = 1000.0
    engine = _a_fleet_of_100(store, cfg, now)

    for _ in range(3):        # warm up — the first tick loads the baselines and the policy
        now += 1
        engine.executor.step(now)
        engine.tick(now)

    durations = []
    for _ in range(20):
        now += 1
        engine.executor.step(now)
        started = time.perf_counter()
        engine.tick(now)
        durations.append((time.perf_counter() - started) * 1000)

    durations.sort()
    p95 = durations[int(len(durations) * 0.95) - 1]
    assert p95 < 200, f"tick p95 was {p95:.1f} ms at 100 agents"


def test_the_tick_writes_one_metric_row_per_agent(tmp_path):
    """The batching must not change *what* is written — only when it is committed."""
    cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")
    store = LocalStore(str(tmp_path / "perf.db"))
    now = 1000.0
    engine = _a_fleet_of_100(store, cfg, now)

    now += 1
    engine.executor.step(now)
    engine.tick(now)

    assert len(store.list_agents()) == 100
    assert len(store.recent_metrics(minutes=10)) == 100
