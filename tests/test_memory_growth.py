"""Fast memory growth alone only warns; a leak is killed when it keeps growing, a one-time jump survives."""
from sentinel.brain import Brain, Verdict, fallback_verdict
from sentinel.collector import AgentState
from sentinel.detector import Level, evaluate
from sentinel.engine import Sentinel
from sentinel.sources import AgentHandle, FakeSource
from shared.config import load_settings
from shared.store import LocalStore

cfg = load_settings()
LIMIT_MB = 512.0


def feed(st: AgentState, readings: list[tuple[float, float]]) -> None:
    for t, mb in readings:
        st.set_memory(mb, 100 * mb / LIMIT_MB, now=t)


def judge(brain: Brain, st: AgentState, now: float) -> Verdict:
    snap = st.snapshot(now)
    finding = evaluate(snap, cfg)
    assert finding.rules == ["memory_growth"], finding.rules
    return brain.judge(snap, finding, [], cfg, now=now)


def fallback_brain() -> Brain:
    return Brain(cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": "", "gemini_api_key": ""}))


def test_one_time_model_load_at_26_percent_survives():
    st, brain = AgentState("alpha", "c", 10**9), fallback_brain()
    feed(st, [(100.0, 70.0), (101.0, 70.0), (102.0, 200.0), (103.0, 201.0), (104.0, 201.0)])   # +130 MB once
    assert 20 < st.snapshot(104.0).memory_pct < 40 and st.snapshot(104.0).memory_pct < cfg.soft_memory_pct
    first = judge(brain, st, 104.0)
    assert first.action == "WARN" and first.pattern == "memory_leak"           # seen, not killed
    feed(st, [(105.0, 201.0), (106.0, 202.0)])                                  # the jump is over: memory is flat
    snap = st.snapshot(106.0)
    assert snap.memory_mb_per_s >= cfg.soft_memory_growth_mb_per_s              # the 5s window still remembers it…
    assert snap.memory_recent_mb_per_s == 0.0                                   # …but it is not growing now
    again = judge(brain, st, 106.0)
    assert again.action == "WARN"                                               # warned twice, never killed


def test_a_leak_that_keeps_growing_is_killed_at_the_next_check():
    st, brain = AgentState("gamma", "c", 10**9), fallback_brain()
    feed(st, [(100.0 + i * 0.5, 40.0 + 17.0 * i) for i in range(6)])           # ~35 MB/s
    first = judge(brain, st, 102.5)
    assert first.action == "WARN" and first.pattern == "memory_leak"
    feed(st, [(103.0 + i * 0.5, 125.0 + 17.0 * (i + 1)) for i in range(6)])    # …and it did not stop
    second = judge(brain, st, 105.5)
    assert second.action == "KILL" and second.pattern == "memory_leak" and second.source == "fallback"


def test_growth_above_the_soft_memory_limit_is_killed_at_once():
    st = AgentState("gamma", "c", 10**9)
    feed(st, [(100.0 + i, 300.0 + 35.0 * i) for i in range(4)])                # 405 MB of 512 = 79%
    snap = st.snapshot(103.0)
    assert snap.memory_pct >= cfg.soft_memory_pct
    v = fallback_verdict(snap, evaluate(snap, cfg), cfg)
    assert v.action == "KILL" and v.pattern == "memory_leak"


def test_a_fast_growing_memory_is_looked_at_again_after_a_few_seconds(tmp_path):
    asked = []

    class Recorder(Brain):
        def __init__(self):
            self.cfg, self.client, self.history = cfg, None, {}

        def judge(self, snap, finding, recent, cfg=None, now=None):
            asked.append(snap.agent)
            return Verdict("WARN", 0.5, "memory_leak", "x", "fallback")

    s = Sentinel(FakeSource(cfg, auto_rogue=None), LocalStore(str(tmp_path / "t.db")), Recorder(), cfg)
    h, st = AgentHandle("c1", "gamma", 10**9), AgentState("gamma", "c1", 10**9)
    snap = st.snapshot(100.0)
    finding = evaluate(snap, cfg)
    finding.rules, finding.level = ["memory_growth"], Level.SUSPICIOUS
    for now in (100.0, 101.0, 102.5, 103.1):
        s._ask_brain(h, st, snap, finding, now)
        for f in list(s.pending.values()):
            f.result(timeout=5)
        s.pending.clear()
    assert len(asked) == 2   # first sight, then once memory_recheck_seconds (3s) have passed — not every tick
