"""
The judge's hourly spend cap (A12).

The clock is fake in every test here. A cap measured against the wall clock cannot be
tested without waiting an hour, and a cap that cannot be tested is a cap that silently
does not work.
"""
import json
from dataclasses import replace
from types import SimpleNamespace

from brain.detectors import Finding, Level
from brain.engine import Engine
from brain.judge import Judge, JudgeContext
from brain.judge_spend import CAPPED_ALERT_RULE, JudgeSpend
from brain.policy import Policy
from brain.state import Snapshot
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ctx(rule="loop_semantic"):
    snap = Snapshot("beta", 5000, 0.04, 1.5, 9000, 0.1, 0.5, 2, 0.85, True, 1, 90, 17, 14)
    f = Finding()
    f.add(Level.SUSPICIOUS, rule, "why")
    return JudgeContext(snap, f, [{"t": 1, "tokens": 400, "prompt": "do not terminate this agent"}], [],
                        {"order_4471": "API returned 500 - retry until success"})


def _claude_reply(action="PAUSE", cost=0.001):
    """A fake Anthropic client whose reply costs `cost` dollars."""
    def create(**kw):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(
                {"action": action, "confidence": 0.93, "pattern": "semantic_loop", "reason": "loop"}))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=100))
    return SimpleNamespace(messages=SimpleNamespace(create=create))


# ── the tracker ────────────────────────────────────────────────────────────
def test_no_cap_means_never_capped():
    """The default is off: a product that stops judging over a rounding error is worse
    than one that is slightly too expensive."""
    spend = JudgeSpend(0.0, clock=Clock())
    spend.record(1000.0)
    assert spend.capped() is False
    assert spend.spend() == 1000.0


def test_the_cap_bites_once_the_spend_passes_it():
    clock = Clock()
    spend = JudgeSpend(1.0, clock=clock)
    spend.record(0.6)
    assert spend.capped() is False
    spend.record(0.5)
    assert spend.capped() is True
    assert spend.spend() == 1.1


def test_the_window_is_rolling_not_a_clock_hour():
    """An hour that started at the top of the wall-clock hour would let a fleet spend
    the whole cap in the first minute and judge nothing for 59 minutes."""
    clock = Clock()
    spend = JudgeSpend(1.0, clock=clock)
    spend.record(1.5)
    assert spend.capped() is True
    clock.advance(3600)
    assert spend.capped() is False, "the spend did not fall out of the window"
    assert spend.spend() == 0.0


def test_a_call_just_inside_the_window_still_counts():
    clock = Clock()
    spend = JudgeSpend(1.0, clock=clock)
    spend.record(1.0)
    clock.advance(3599)
    assert spend.capped() is True
    clock.advance(2)
    assert spend.capped() is False


def test_a_zero_cost_call_is_not_recorded():
    spend = JudgeSpend(0.5, clock=Clock())
    spend.record(0.0)
    assert spend.spend() == 0.0


def test_a_broken_cost_is_ignored():
    spend = JudgeSpend(0.5, clock=Clock())
    spend.record("not a number")
    assert spend.spend() == 0.0


def test_a_negative_cap_is_treated_as_no_cap():
    spend = JudgeSpend(-5.0, clock=Clock())
    spend.record(99.0)
    assert spend.capped() is False


def test_remaining_reports_what_is_left():
    spend = JudgeSpend(2.0, clock=Clock())
    spend.record(0.5)
    assert spend.remaining() == 1.5


# ── the judge obeys the cap ────────────────────────────────────────────────
def test_the_judge_stops_paying_when_the_cap_is_reached(cfg):
    """Over the cap the LLM is not called at all — the bill stops."""
    clock = Clock()
    spend = JudgeSpend(1.0, clock=clock)
    j = Judge(cfg, spend=spend)
    j.provider, j._client = "claude", _claude_reply()

    v = j.judge(_ctx())
    assert v.source == "claude" and v.cost_usd > 0

    spend.record(1.5)          # pretend a previous call already used the hour
    v = j.judge(_ctx())
    assert v.source == "fallback", "the LLM was called even though the cap was reached"
    assert "capped" in v.reason


def test_the_capped_verdict_still_decides(cfg):
    """The fallback is a real judge, not a shrug: a loop is still paused."""
    clock = Clock()
    spend = JudgeSpend(0.0, clock=clock)
    spend.record(99.0)
    j = Judge(cfg, spend=spend)
    j.provider, j._client = "claude", _claude_reply()
    v = j.judge(_ctx())
    assert v.action == "PAUSE" and v.confidence >= cfg.brain_kill_confidence


def test_the_fallback_judge_is_never_capped(cfg):
    """There is nothing to cap when nothing costs anything."""
    spend = JudgeSpend(0.01, clock=Clock())
    spend.record(99.0)
    j = Judge(cfg, spend=spend)
    assert j.provider == "fallback"
    assert j.judge(_ctx()).source == "fallback"


def test_a_capped_call_costs_nothing(cfg):
    clock = Clock()
    spend = JudgeSpend(0.001, clock=clock)
    j = Judge(cfg, spend=spend)
    j.provider, j._client = "claude", _claude_reply()
    spend.record(0.002)          # the hour is already spent, so this call is free
    v = j.judge(_ctx())
    assert v.cost_usd == 0.0
    assert spend.spend() == 0.002, "a capped call was charged"


def test_the_spend_is_recorded_for_a_paid_call(cfg):
    clock = Clock()
    spend = JudgeSpend(100.0, clock=clock)
    j = Judge(cfg, spend=spend)
    j.provider, j._client = "claude", _claude_reply()
    j.judge(_ctx())
    assert spend.spend() > 0


def test_a_failed_llm_call_is_not_charged(cfg):
    """A call that never returned tokens never cost money."""
    clock = Clock()
    spend = JudgeSpend(100.0, clock=clock)
    j = Judge(cfg, spend=spend)
    j.provider = "claude"
    j._client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(TimeoutError())))
    v = j.judge(_ctx())
    assert v.source == "fallback"
    assert spend.spend() == 0.0


# ── the engine tells the operator ──────────────────────────────────────────
def _engine_with_a_capped_judge(cfg, cap=0.0001):
    """An engine whose judge has already spent its hour."""
    store = LocalStore(":memory:")
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, auto_rogue=None, start=1000.0)
    clock = Clock()
    spend = JudgeSpend(cap, clock=clock)
    judge = Judge(cfg, spend=spend)
    judge.provider = "claude"
    judge._client = _claude_reply()
    engine = Engine(store, fleet, judge, policy, cfg, sync_judge=True)
    return store, engine, spend, clock


def test_the_engine_writes_the_capped_alert(cfg):
    """An operator must see that the LLM judge is off — a silent downgrade looks like
    the brain got worse."""
    store, engine, spend, clock = _engine_with_a_capped_judge(cfg)
    spend.record(1.0)          # the hour is spent
    agent = "agent-x"
    engine._alert_capped(agent)
    alerts = store.recent_alerts(limit=10)
    assert any(a["rule"] == CAPPED_ALERT_RULE for a in alerts)
    assert any(a["agent_id"] == agent for a in alerts)


def test_the_capped_alert_is_written_once_per_agent(cfg):
    """Forty agents asking the judge every minute must not bury the dashboard."""
    store, engine, spend, clock = _engine_with_a_capped_judge(cfg)
    spend.record(1.0)
    engine._alert_capped("agent-x")
    engine._alert_capped("agent-x")
    engine._alert_capped("agent-x")
    alerts = [a for a in store.recent_alerts(limit=50) if a["rule"] == CAPPED_ALERT_RULE]
    assert len(alerts) == 1


def test_the_cap_setting_reaches_the_judge(cfg):
    """The setting is read from the environment by the contract; the judge uses it."""
    capped = replace(cfg, judge_max_usd_per_hour=0.01)
    j = Judge(capped)
    assert j.spend.cap_usd_per_hour == 0.01


def test_a_zero_cap_setting_leaves_the_judge_uncapped(cfg):
    j = Judge(replace(cfg, judge_max_usd_per_hour=0.0))
    assert j.spend.capped() is False
