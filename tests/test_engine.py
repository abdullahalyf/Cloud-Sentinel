"""End-to-end with fake agents + in-memory SQLite. No Docker, no network."""
import time

from sentinel.brain import Brain, Verdict
from sentinel.engine import Sentinel
from sentinel.sources import FakeSource, parse_docker_ts
from shared.config import load_settings
from shared.contracts import CommandRow
from shared.store import LocalStore

cfg = load_settings()


class FixedBrain(Brain):
    def __init__(self, verdict):
        self.cfg, self.client, self.verdict, self.calls = cfg, None, verdict, 0

    def judge(self, snap, finding, recent):
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
