"""FakeSource: a rogue agent starts looping right away, so the loop count climbs 1, 2, 3, 4, 5…"""
from sentinel.collector import AgentState
from sentinel.sources import ROGUE_INJECTION, ROGUE_PROMPT, FakeSource
from shared.config import load_settings

cfg = load_settings()


def test_overdue_healthy_call_does_not_delay_the_loop(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("sentinel.sources.time.time", lambda: clock[0])
    source = FakeSource(cfg, names=("beta",), auto_rogue=None)
    h = source.list_agents()[0]
    source.agents["beta"].next_call = 99.0  # a healthy call is overdue
    source.go_rogue(h)
    events = source.read_events(h)
    assert events[0].ts == 99.0 and events[0].prompt not in (ROGUE_PROMPT, ROGUE_INJECTION)
    assert events[1].ts == 100.0 and events[1].prompt in (ROGUE_PROMPT, ROGUE_INJECTION)


def test_first_loop_flag_at_exactly_the_threshold(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("sentinel.sources.time.time", lambda: clock[0])
    source = FakeSource(cfg, names=("beta",), auto_rogue=None)
    h = source.list_agents()[0]
    source.agents["beta"].next_call = 99.0
    source.go_rogue(h)
    st, counts = AgentState("beta", h.id, h.token_budget), []
    for _ in range(15):  # 1s ticks, like the engine
        for e in source.read_events(h):
            st.add(e)
        counts.append(st.snapshot(clock[0]).loop_repeats)
        clock[0] += 1.0
    assert cfg.loop_repeat_threshold in counts  # no jump past the threshold
