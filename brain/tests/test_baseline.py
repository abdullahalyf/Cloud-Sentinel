"""
A4: adaptive per-agent baselines. Acceptance tests.

A fixed soft limit is wrong for every agent but one. These tests check that:
  - a stable high-usage agent (a gamma-like analyst) never trips
  - a 3× spike over its OWN baseline trips, even under the fixed limits
  - the warmup uses the fixed soft limits
  - a restart restores the baseline
  - a legit burst is not paused
"""
from dataclasses import replace

import pytest

from brain.baseline import AgentBaseline, Baseline, describe
from brain.detectors import Level, evaluate
from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from brain.state import Snapshot
from shared.config import settings
from shared.contracts import AgentRow
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore

# ── helpers ───────────────────────────────────────────────────────────────────


def snap(agent="beta", tokens=1000, usd=0.01, calls=0.5, **kw) -> Snapshot:
    return Snapshot(agent, tokens, usd, calls, tokens, 0.0, 1.0, 0, 0.0, False, 0, 50.0, 10.0, 10, **kw)


def feed(baseline: AgentBaseline, value: float, times: int, cfg, metric="tokens_per_min") -> None:
    """Give the baseline `times` identical healthy samples."""
    for i in range(times):
        baseline.observe(1000.0 + i, {metric: value})
    baseline.recompute(cfg)


# ── the maths ────────────────────────────────────────────────────────────────


def test_the_median_and_the_mad_are_robust_to_one_spike(cfg):
    """One huge sample must not move the median or inflate the spread much."""
    b = AgentBaseline("beta")
    for i in range(20):
        b.observe(1000.0 + i, {"tokens_per_min": 10_000.0})
    b.observe(1020.0, {"tokens_per_min": 900_000.0})   # the spike
    b.recompute(cfg)
    assert b.metrics["tokens_per_min"].median == pytest.approx(10_000.0)
    assert b.metrics["tokens_per_min"].mad == pytest.approx(0.0)


def test_the_limit_is_the_median_plus_k_mad(cfg):
    b = AgentBaseline("beta")
    for i in range(10):
        b.observe(1000.0 + i, {"tokens_per_min": 10_000.0})
    for i in range(10):
        b.observe(1010.0 + i, {"tokens_per_min": 14_000.0})
    b.recompute(cfg)
    m = b.metrics["tokens_per_min"]
    assert m.median == pytest.approx(12_000.0)
    assert m.mad == pytest.approx(2_000.0)
    # the spread is floored at a quarter of the median, so the limit is not tighter than that
    spread = max(m.mad, m.median * 0.25)
    assert m.limit == pytest.approx(12_000.0 + cfg.baseline_k * 1.4826 * spread)


def test_the_limit_never_exceeds_the_hard_limit(cfg):
    """A wildly spread-out agent must not get a limit above the hard one."""
    b = AgentBaseline("beta")
    for i in range(20):
        b.observe(1000.0 + i, {"tokens_per_min": float(i) * 10_000})
    b.recompute(cfg)
    assert b.limit("tokens_per_min") <= cfg.hard_tokens_per_min


def test_the_limit_never_drops_below_a_quarter_of_the_soft_limit(cfg):
    """A very quiet agent must still be allowed to do real work."""
    b = AgentBaseline("beta")
    for i in range(20):
        b.observe(1000.0 + i, {"tokens_per_min": 1.0})
    b.recompute(cfg)
    assert b.limit("tokens_per_min") >= cfg.soft_tokens_per_min * 0.25


def test_the_baseline_ignores_a_value_it_cannot_use(cfg):
    """A broken sample (NaN, negative, not a number) never enters the baseline."""
    b = AgentBaseline("beta")
    for i in range(20):
        b.observe(1000.0 + i, {"tokens_per_min": 10_000.0})
    b.observe(1020.0, {"tokens_per_min": float("nan")})
    b.observe(1021.0, {"tokens_per_min": -5.0})
    b.observe(1022.0, {"tokens_per_min": "not a number"})
    b.observe(1023.0, {"calls_per_sec": 0.5})   # only one metric — the others are untouched
    b.recompute(cfg)
    assert b.metrics["tokens_per_min"].samples == 20
    assert b.metrics["tokens_per_min"].median == pytest.approx(10_000.0)


# ── the detector uses the baseline ───────────────────────────────────────────


def test_a_3x_spike_over_its_own_baseline_trips_even_under_the_fixed_limits(cfg):
    """The whole point: the fixed soft limit is 25k, so 20k is 'fine' — for this agent it is not."""
    b = AgentBaseline("beta")
    feed(b, 5_000, 30, cfg)
    assert b.limit("tokens_per_min") < cfg.soft_tokens_per_min

    # 3× its own normal, but still under the fixed soft limit
    finding = evaluate(snap(tokens=16_000), cfg, baseline=b)
    assert finding.level == Level.SUSPICIOUS
    assert "token_spike" in finding.rules
    assert "above this agent's normal" in finding.text

    # the same value WITHOUT a baseline is fine
    assert evaluate(snap(tokens=16_000), cfg).level == Level.OK


def test_a_stable_high_usage_agent_never_trips(cfg):
    """A busy analyst: high, but normal for it. The fixed limit would stop it."""
    b = AgentBaseline("gamma")
    feed(b, 40_000, 30, cfg)
    # 45k tokens/min is over the fixed soft limit (25k) but normal for this agent
    finding = evaluate(snap("gamma", tokens=45_000), cfg, baseline=b)
    assert finding.level == Level.OK


def test_the_hard_limit_is_never_moved_by_a_baseline(cfg):
    """A baseline makes the soft limits adaptive — never the hard ones."""
    b = AgentBaseline("beta")
    feed(b, 100_000, 30, cfg)
    finding = evaluate(snap(tokens=cfg.hard_tokens_per_min + 1), cfg, baseline=b)
    assert finding.level == Level.CRITICAL
    assert "token_rate_hard" in finding.rules


def test_the_finding_text_says_how_far_above_its_normal_the_agent_is(cfg):
    b = AgentBaseline("beta")
    feed(b, 4_000, 30, cfg)
    finding = evaluate(snap(tokens=12_000), cfg, baseline=b)
    assert "3.0× above this agent's normal" in finding.text


def test_describe_without_a_baseline_says_nothing():
    assert describe(100.0, None, "tokens_per_min") == ""
    assert describe(100.0, Baseline(median=0, samples=5), "tokens_per_min") == ""


# ── the engine: warmup, learning, restart ────────────────────────────────────


def make_sim(cfg, store=None, fleet=None, names=("alpha", "beta", "gamma", "delta")):
    store = store or LocalStore(":memory:")
    fleet = fleet or FakeFleet(store, names=names, auto_rogue=None, start=1000.0)
    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)
    return store, fleet, engine


def test_the_warmup_uses_the_fixed_soft_limits(cfg):
    """During the warmup the baseline is learned but NOT used — the fixed limits decide."""
    cfg = replace(cfg, baseline_warmup_seconds=60.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(30):
        now += 1
        fleet.step(now)
        engine.tick(now)
    # still warming up → the baseline is not used for detection
    assert engine._baseline_for("alpha", now) is None
    # but it IS being learned, so the agent has a normal by the time the warmup ends
    assert engine.baselines["alpha"].ready()


def test_an_agent_learns_its_baseline_after_the_warmup(cfg):
    cfg = replace(cfg, baseline_warmup_seconds=10.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(40):
        now += 1
        fleet.step(now)
        engine.tick(now)
    baseline = engine.baselines.get("alpha")
    assert baseline is not None and baseline.ready()
    assert baseline.metrics["tokens_per_min"].samples > 0
    # and it is kept in the store, so a restart does not forget it
    assert store.get_agent("alpha")["baseline"]["tokens_per_min"]["limit"] > 0


def test_a_restart_restores_the_baseline(cfg):
    cfg = replace(cfg, baseline_warmup_seconds=10.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(40):
        now += 1
        fleet.step(now)
        engine.tick(now)
    learned = engine.baselines["alpha"].to_dict()

    # a new brain over the SAME store (a restart) picks the baseline back up
    _, _, restarted = make_sim(cfg, store=store, fleet=fleet)
    assert "alpha" in restarted.baselines
    assert restarted.baselines["alpha"].to_dict() == learned


def test_a_learned_baseline_survives_the_agent_row_being_written_again(cfg):
    """The brain writes the agents row every tick — that must not wipe the baseline."""
    cfg = replace(cfg, baseline_warmup_seconds=1.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(20):
        now += 1
        fleet.step(now)
        engine.tick(now)
    assert store.get_agent("alpha")["baseline"]
    store.upsert_agent(AgentRow("alpha", state="healthy"))
    assert store.get_agent("alpha")["baseline"]


def test_the_engine_flags_a_spike_over_its_own_normal_that_the_fixed_limit_ignores(cfg):
    """
    The end-to-end acceptance case: a quiet agent that suddenly goes 3× over its own
    normal is flagged — even though it is still well under the fixed soft limit, so
    the fixed limits would never have noticed.
    """
    cfg = replace(cfg, baseline_warmup_seconds=10.0)
    store, fleet, engine = make_sim(cfg, names=("alpha",))
    now = 1000.0
    for _ in range(30):
        now += 1
        fleet.step(now)
        engine.tick(now)
    baseline = engine.baselines["alpha"]
    assert baseline.ready()
    quiet = baseline.metrics["tokens_per_min"].median
    # The window where the baseline adds value: above the agent's own limit, but still
    # under the fixed soft limit — where the fixed limits would never have noticed.
    limit = baseline.limit("tokens_per_min")
    assert limit < cfg.soft_tokens_per_min, "the agent's own limit must be tighter than the fixed one"
    spike = limit + (cfg.soft_tokens_per_min - limit) * 0.5
    assert spike < cfg.soft_tokens_per_min, "the spike must stay under the fixed limit"
    assert spike > quiet * 2, "the spike must be well above this agent's normal"

    # the detector now uses the agent's own normal
    finding = evaluate(snap("alpha", tokens=int(spike)), cfg, baseline=baseline)
    assert "token_spike" in finding.rules
    assert "above this agent's normal" in finding.text
    # and without the baseline the same value is fine
    assert evaluate(snap("alpha", tokens=int(spike)), cfg).level == Level.OK


def test_a_paused_agent_does_not_teach_the_brain_a_new_normal(cfg):
    """A runaway must never become 'the normal' the baseline learns."""
    cfg = replace(cfg, baseline_warmup_seconds=5.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(20):
        now += 1
        fleet.step(now)
        engine.tick(now)
    before = engine.baselines["beta"].metrics["tokens_per_min"].median

    fleet.go_rogue("beta", "token_bomb", now)
    for _ in range(15):
        now += 1
        fleet.step(now)
        engine.tick(now)
    assert engine.breakers["beta"].state in ("paused", "killed")
    after = engine.baselines["beta"].metrics["tokens_per_min"].median
    assert after <= before * 2   # the median did not run away with the spike


def test_a_legit_burst_is_not_paused(cfg):
    """The false-positive check: a busy but healthy agent stays healthy."""
    cfg = replace(cfg, baseline_warmup_seconds=5.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(40):
        now += 1
        fleet.step(now)
        engine.tick(now)
    assert all(b.state == "healthy" for b in engine.breakers.values())
    assert not [a for a in store.recent_actions() if a["action"] in ("PAUSE", "KILL")]


def test_the_baseline_can_be_switched_off(cfg):
    """CS_BASELINE_ENABLED=false → the fixed soft limits only."""
    cfg = replace(cfg, baseline_enabled=False, baseline_warmup_seconds=1.0)
    store, fleet, engine = make_sim(cfg)
    now = 1000.0
    for _ in range(30):
        now += 1
        fleet.step(now)
        engine.tick(now)
    assert not engine.baselines or all(not b.ready() for b in engine.baselines.values())
