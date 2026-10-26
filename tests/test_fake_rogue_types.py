"""Fake mode can play every ROGUE_TYPE of agents/agent.py; each one is killed, healthy agents survive."""
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.sources import ROGUE_TYPES, FakeSource
from shared.config import load_settings
from shared.store import LocalStore

cfg = replace(load_settings(), anthropic_api_key="", gemini_api_key="", webhook_url="")
ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("rogue_type", ROGUE_TYPES)
def test_every_rogue_type_is_killed_in_fake_mode_and_healthy_agents_survive(tmp_path, rogue_type):
    store = LocalStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None, rogue_type=rogue_type)
    s = Sentinel(source, store, Brain(cfg), cfg)
    beta = source.agents["beta"]
    beta.go_rogue()
    started = time.time()
    while beta.alive and time.time() - started < 14:
        s.tick()
        for f in list(s.pending.values()):
            f.result(timeout=5)
        time.sleep(0.2)
    assert not beta.alive, f"{rogue_type} was not killed"
    assert source.agents["alpha"].alive and source.agents["gamma"].alive
    kills = [a for a in store.recent_actions() if a["action"] == "KILL"]
    assert [k["agent"] for k in kills] == ["beta"]


def test_rogue_types_look_like_the_real_agent():
    for rogue_type, check in {
        "token_bomb": lambda ev: ev.tokens >= 5000 and "full conversation history" in ev.prompt,
        "paraphrase_loop": lambda ev: "4471" in ev.prompt and 360 <= ev.tokens <= 430,
        "memory_leak": lambda ev: "(job " in ev.prompt and ev.tokens <= 700,
        "loop": lambda ev: "order #4471" in ev.prompt,
    }.items():
        source = FakeSource(cfg, auto_rogue=None, rogue_type=rogue_type)
        a = source.agents["beta"]
        a.rogue_since = time.time() - 3
        event, gap = source._rogue_call(a, time.time())
        assert check(event), (rogue_type, event)
        assert 0 < gap <= 1.5


def test_only_the_leaker_and_the_loop_grow_memory():
    for rogue_type, grows in {"memory_leak": True, "loop": True, "token_bomb": False, "paraphrase_loop": False}.items():
        source = FakeSource(cfg, auto_rogue=None, rogue_type=rogue_type)
        a = source.agents["beta"]
        before = source.read_memory(source.list_agents()[1])[0]
        a.rogue_since = time.time() - 6
        assert (source.read_memory(source.list_agents()[1])[0] - before > 30) == grows, rogue_type


def test_unknown_rogue_type_is_refused():
    with pytest.raises(ValueError):
        FakeSource(cfg, rogue_type="bogus")
    result = subprocess.run([sys.executable, "-m", "sentinel", "--fake", "--rogue-type", "bogus"],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "invalid choice" in result.stderr


def test_default_rogue_type_is_loop():
    assert FakeSource(cfg).agents["beta"].rogue_type == "loop"
