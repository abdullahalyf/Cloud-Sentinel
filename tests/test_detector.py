from sentinel.collector import AgentState
from sentinel.detector import Level, evaluate
from shared.config import load_settings
from shared.contracts import AgentEvent

cfg = load_settings()
NOW = 1_000_000.0


def state_with(calls, budget=150_000):
    st = AgentState("beta", "c1", budget)
    for ts, tokens, prompt in calls:
        st.add(AgentEvent("beta", "llm_call", ts, tokens_in=tokens, prompt=prompt))
    return st


def test_healthy_agent_is_ok():
    calls = [(NOW - 50 + i * 4, 400, f"task {i}") for i in range(12)]
    f = evaluate(state_with(calls).snapshot(NOW), cfg)
    assert f.level == Level.OK, f.reasons


def test_loop_is_suspicious():
    calls = [(NOW - 10 + i, 300, "same prompt") for i in range(10)]
    snap = state_with(calls).snapshot(NOW)
    f = evaluate(snap, cfg)
    assert snap.loop_repeats == 10
    assert f.level == Level.SUSPICIOUS
    assert "loop_detected" in f.rules


def test_hard_token_rate_is_critical():
    # 30 calls × 600 tokens in 10s → ~108k tokens/min
    calls = [(NOW - 10 + i / 3, 600, f"p{i}") for i in range(30)]
    f = evaluate(state_with(calls).snapshot(NOW), cfg)
    assert f.level == Level.CRITICAL
    assert "token_rate_hard" in f.rules


def test_budget_exceeded_is_critical():
    calls = [(NOW - 30, 2_000, "x")]
    f = evaluate(state_with(calls, budget=1_000).snapshot(NOW), cfg)
    assert f.level == Level.CRITICAL
    assert "budget_exceeded" in f.rules


def test_memory_hard_is_critical():
    st = state_with([])
    st.set_memory(480, 95)
    assert evaluate(st.snapshot(NOW), cfg).level == Level.CRITICAL


def test_old_events_fall_out_of_window():
    calls = [(NOW - 500 + i, 300, "same") for i in range(20)]
    snap = state_with(calls).snapshot(NOW)
    assert snap.loop_repeats == 0 and snap.tokens_per_min == 0
