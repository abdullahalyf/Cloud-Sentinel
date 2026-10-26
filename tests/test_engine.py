"""End-to-end with fake agents + in-memory SQLite. No Docker, no network."""
import time

import pytest

from sentinel.brain import Brain, Verdict
from sentinel.engine import Sentinel
from sentinel.sources import FakeSource, parse_docker_ts
from shared.config import load_settings
from shared.contracts import CommandRow
from shared.store import LocalStore

cfg = load_settings()


class FixedBrain(Brain):
    def __init__(self, verdict):
        self.cfg, self.client, self.verdict, self.calls, self.history = cfg, None, verdict, 0, {}

    def judge(self, snap, finding, recent, cfg=None):
        self.calls += 1
        return self.verdict


def make(tmp_path, verdict=None):
    store = LocalStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None)
    brain = FixedBrain(verdict) if verdict else Brain(cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": ""}))
    return Sentinel(source, store, brain, cfg), source, store


def run_ticks(s, seconds):
    end = time.time() + seconds
    while time.time() < end:
        s.tick()
        for f in list(s.pending.values()):
            f.result(timeout=5)  # let the brain thread finish
        time.sleep(0.2)


def test_rogue_agent_gets_killed_by_brain(tmp_path):
    s, source, store = make(tmp_path)  # real fallback brain (no API key)
    source.agents["beta"].rogue_since = time.time() - 15  # pretend it went rogue 15s ago
    source.agents["beta"].next_call = time.time() - 15
    run_ticks(s, 2)
    assert not source.agents["beta"].alive
    assert source.agents["alpha"].alive and source.agents["gamma"].alive
    kills = [a for a in store.recent_actions() if a["action"] == "KILL"]
    assert [k["agent"] for k in kills] == ["beta"]


def test_brain_ignore_does_not_kill(tmp_path):
    s, source, store = make(tmp_path, Verdict("IGNORE", 0.9, "legitimate_burst", "fine", "claude"))
    source.agents["beta"].rogue_since = time.time() - 6
    source.agents["beta"].next_call = time.time() - 6
    run_ticks(s, 1)
    assert source.agents["beta"].alive


def test_human_kill_switch(tmp_path):
    s, source, store = make(tmp_path)
    s.tick()
    store.insert_command(CommandRow("gamma", "KILL", "dashboard", "test"))
    s.tick()
    assert not source.agents["gamma"].alive
    assert store.pending_commands() == []
    assert store.recent_actions()[0]["actor"] == "human"


def test_dry_run_never_kills(tmp_path):
    s, source, store = make(tmp_path)
    s.dry_run = True
    store.insert_command(CommandRow("alpha", "KILL"))
    s.tick()
    assert source.agents["alpha"].alive


def test_docker_timestamp_parsing_orders_correctly():
    a = parse_docker_ts("2026-10-25T12:00:00.100000000Z")
    b = parse_docker_ts("2026-10-25T12:00:00.123Z")
    assert a < b


def test_brain_kills_rogue_within_10s_before_hard_limits(tmp_path):
    s, source, store = make(tmp_path)  # real fallback brain (no API key)
    s.tick()
    source.go_rogue(next(h for h in source.list_agents() if h.name == "beta"))
    started = time.time()
    while source.agents["beta"].alive and time.time() - started < 10:
        run_ticks(s, 1)
    assert not source.agents["beta"].alive
    assert source.agents["alpha"].alive and source.agents["gamma"].alive
    kills = [a for a in store.recent_actions() if a["action"] == "KILL"]
    assert [(k["agent"], k["actor"]) for k in kills] == [("beta", "fallback")]  # brain, not hard rules


def test_pause_quarantines_and_resume_restarts_judging(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from sentinel import engine

    s, source, store = make(tmp_path)
    store.insert_command(CommandRow('beta', 'PAUSE', reason='Review runaway agent'))
    evaluate = Mock(side_effect=AssertionError('paused agent was judged'))
    real_evaluate = engine.evaluate
    monkeypatch.setattr(engine, 'evaluate', evaluate)
    # Only beta remains, so any evaluation means quarantine failed.
    source.agents['alpha'].alive = source.agents['gamma'].alive = False
    s.tick()
    assert source.agents['beta'].alive
    assert source.is_paused(source.list_agents()[0])
    assert store.recent_metrics()[-1]['status'] == 'paused'
    assert store.recent_actions()[0]['action'] == 'PAUSE'
    assert store.recent_actions()[0]['reason'] == 'Review runaway agent'
    assert not store.pending_commands()
    evaluate.assert_not_called()
    monkeypatch.setattr(engine, 'evaluate', real_evaluate)
    store.insert_command(CommandRow('beta', 'RESUME'))
    s.tick()
    assert not source.is_paused(source.list_agents()[0])
    assert store.recent_metrics()[-1]['status'] == 'running'
    assert not store.pending_commands()
    s.pool.shutdown()


@pytest.mark.parametrize("future_state", ["pending", "running", "done"])
def test_pause_discards_pending_kill_verdict(tmp_path, future_state):
    from concurrent.futures import Future

    s, source, store = make(tmp_path)
    s.tick()
    pending = Future()
    if future_state == 'running':
        pending.set_running_or_notify_cancel()
    elif future_state == 'done':
        pending.set_result(Verdict('KILL', 1.0, 'loop', 'stale verdict', 'claude'))
    s.pending['fake-beta'] = pending
    store.insert_command(CommandRow('beta', 'PAUSE'))
    s.tick()
    assert 'fake-beta' not in s.pending
    if future_state == 'running':
        pending.set_result(Verdict('KILL', 1.0, 'loop', 'stale verdict', 'claude'))
    store.insert_command(CommandRow('beta', 'RESUME'))
    s.tick()
    assert source.agents['beta'].alive
    assert not any(a['action'] == 'KILL' for a in store.recent_actions())
    s.pool.shutdown()


def test_pause_failure_does_not_record_action(tmp_path, monkeypatch):
    s, source, store = make(tmp_path)
    def fail(h):
        raise RuntimeError('Docker pause denied')
    monkeypatch.setattr(source, 'pause', fail)
    store.insert_command(CommandRow('beta', 'PAUSE'))
    s.tick()
    assert not source.is_paused(source.list_agents()[1])
    assert store.recent_actions() == []
    assert not store.pending_commands()
    assert store._select('select status, result from commands')[0] == {
        'status': 'failed', 'result': 'Docker pause denied'}
    s.pool.shutdown()


def test_dry_run_does_not_pause_or_resume(tmp_path):
    s, source, store = make(tmp_path)
    s.dry_run = True
    store.insert_command(CommandRow('alpha', 'PAUSE'))
    s.tick()
    h = source.list_agents()[0]
    assert not source.is_paused(h)
    source.pause(h)
    store.insert_command(CommandRow('alpha', 'RESUME'))
    s.tick()
    assert source.is_paused(h)
    assert store.recent_actions() == []
    assert [r['status'] for r in store._select('select status from commands')] == ['failed', 'failed']
    s.pool.shutdown()


def test_emergency_kill_still_works_when_paused(tmp_path):
    s, source, store = make(tmp_path)
    store.insert_command(CommandRow('beta', 'PAUSE'))
    s.tick()
    store.insert_command(CommandRow('beta', 'KILL'))
    s.tick()
    assert not source.agents['beta'].alive
    assert store.recent_actions()[0]['action'] == 'KILL'
    s.pool.shutdown()


def test_rogue_command_while_paused_fails_without_executing(tmp_path, monkeypatch):
    from unittest.mock import Mock

    s, source, store = make(tmp_path)
    rogue = Mock(side_effect=AssertionError('must not exec in a paused container'))
    monkeypatch.setattr(source, 'go_rogue', rogue)
    store.insert_command(CommandRow('beta', 'PAUSE'))
    store.insert_command(CommandRow('beta', 'GO_ROGUE'))
    s.tick()
    rogue.assert_not_called()
    assert [r['status'] for r in store._select('select status from commands order by id')] == ['done', 'failed']
    s.pool.shutdown()


def test_resume_failure_keeps_agent_quarantined(tmp_path, monkeypatch):
    s, source, store = make(tmp_path)
    store.insert_command(CommandRow('beta', 'PAUSE'))
    s.tick()
    def fail(h):
        raise RuntimeError('Docker unpause denied')
    monkeypatch.setattr(source, 'resume', fail)
    store.insert_command(CommandRow('beta', 'RESUME'))
    s.tick()
    assert source.is_paused(source.list_agents()[1])
    assert store._select('select status from commands order by id')[-1]['status'] == 'failed'
    assert [m for m in store.recent_metrics() if m['agent'] == 'beta'][-1]['status'] == 'paused'
    s.pool.shutdown()


def test_kill_clears_brain_history(tmp_path):
    s, source, store = make(tmp_path)
    s.brain.history["beta"] = ["old verdict"]
    h = next(h for h in source.list_agents() if h.name == "beta")
    assert s.kill(h, actor="human", reason="test")
    assert "beta" not in s.brain.history


def test_new_rule_skips_brain_cooldown(tmp_path):
    from sentinel.collector import AgentState
    from sentinel.detector import Finding, Level

    s, source, store = make(tmp_path, Verdict("WARN", 0.5, "other", "hm", "fallback"))
    h = source.list_agents()[0]
    st = AgentState(h.name, h.id, 1000)
    snap = st.snapshot()
    first, same, more = Finding(), Finding(), Finding()
    first.add(Level.SUSPICIOUS, "prompt_injection", "x")
    same.add(Level.SUSPICIOUS, "prompt_injection", "x")
    more.add(Level.SUSPICIOUS, "loop_detected", "y")
    more.add(Level.SUSPICIOUS, "prompt_injection", "x")
    now = time.time()
    for finding, t in ((first, now), (same, now + 2), (more, now + 3)):
        s._ask_brain(h, st, snap, finding, t)
        fut = s.pending.pop(h.id, None)
        if fut:
            fut.result(timeout=5)
    assert s.brain.calls == 2   # same rules waited for the cooldown, a new rule did not


def test_no_brain_call_after_a_kill(tmp_path):
    s, source, store = make(tmp_path, Verdict("KILL", 0.9, "infinite_loop", "loop", "claude"))
    s.cfg = cfg.__class__(**{**cfg.__dict__, "brain_cooldown_seconds": 0.0})  # cooldown can't hide it
    source.agents["beta"].rogue_since = time.time() - 15
    source.agents["beta"].next_call = time.time() - 15
    run_ticks(s, 1)
    assert not source.agents["beta"].alive
    assert s.brain.calls == 1 and not s.pending
