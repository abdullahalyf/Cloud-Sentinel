"""Tests for agents/agent.py, the simulated AI agent. No Docker, and nothing really sleeps."""
import random
import time

import pytest

from agents import agent
from shared.contracts import AgentEvent

ROGUE_FUNCTIONS = ("rogue_loop", "rogue_token_bomb", "rogue_memory_leak", "rogue_paraphrase_loop")


class Stop(Exception):
    """Raised by a fake to break out of agent.main(), which loops forever."""


@pytest.fixture(autouse=True)
def fast_and_repeatable(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    random.seed(1234)


def events(capsys):
    """Every contract line the agent printed, parsed back the way the sentinel does it."""
    lines = capsys.readouterr().out.splitlines()
    return [e for e in (AgentEvent.parse_line(line) for line in lines) if e]


def recorder(called, name):
    def fake(*args):
        called.append(name)
        raise Stop

    return fake


# ── what each behaviour prints ───────────────────────────────────────────────
def test_healthy_call_follows_the_contract(capsys):
    agent.healthy_call()
    [e] = events(capsys)
    assert e.type == "llm_call" and e.agent == agent.NAME and e.prompt
    assert 150 <= e.tokens <= 700


def test_loop_repeats_the_same_prompt(capsys, monkeypatch):
    monkeypatch.setattr(agent, "LEAK_CAP_MB", 1)
    leak = []
    for _ in range(5):
        agent.rogue_loop(1.0, leak)
    assert {e.prompt for e in events(capsys)} == {agent.LOOP_PROMPT}


def test_token_bomb_burns_5k_to_15k_tokens_per_call_with_different_prompts(capsys):
    for _ in range(40):
        agent.rogue_token_bomb(1.0)
    evs = events(capsys)
    assert len(evs) == 40
    assert all(5_000 <= e.tokens <= 15_000 for e in evs)
    assert len({e.prompt for e in evs}) > 1          # not a loop: the "same prompt" rule must not fire


def test_memory_leak_calls_look_healthy(capsys, monkeypatch):
    monkeypatch.setattr(agent, "LEAK_CAP_MB", 1)
    leak = []
    for _ in range(5):
        agent.rogue_memory_leak(1.0, leak)
    evs = events(capsys)
    assert len(evs) == 5 and all(e.tokens <= 700 for e in evs)


def test_leak_ram_grabs_real_memory_and_respects_the_cap(monkeypatch):
    monkeypatch.setattr(agent, "LEAK_CAP_MB", 3)
    leak = []
    for _ in range(10):
        agent.leak_ram(leak, 1)
    assert len(leak) == 3                            # 1 + 1 + 1 MB, then it stops
    assert len(leak[0]) == 1024 * 1024
    assert leak[0][0] == ord("x") and leak[0][-1] == ord("x")  # filled, so the OS really gives the RAM


def test_paraphrase_loop_is_the_same_task_in_new_words_every_time(capsys):
    for _ in range(100):
        agent.rogue_paraphrase_loop(1.0)
    prompts = [e.prompt for e in events(capsys)]
    assert len(prompts) == 100
    assert all("4471" in p for p in prompts)                      # always the same job
    assert all(a != b for a, b in zip(prompts, prompts[1:]))      # never the same text twice in a row
    assert max(prompts.count(p) for p in set(prompts)) < 8        # the repeat-counter (threshold 8) is blind


def test_paraphrase_loop_is_about_400_tokens_per_call(capsys):
    agent.rogue_paraphrase_loop(1.0)
    [e] = events(capsys)
    assert 360 <= e.tokens <= 430


# ── when does an agent go rogue? ─────────────────────────────────────────────
def test_is_rogue_triggers(monkeypatch, tmp_path):
    flag = tmp_path / "go_rogue"
    monkeypatch.setattr(agent, "MODE", "normal")
    monkeypatch.setattr(agent, "ROGUE_AFTER", 0.0)
    monkeypatch.setattr(agent, "FLAG_FILE", str(flag))
    now = time.time()
    assert not agent.is_rogue(now)                   # healthy

    monkeypatch.setattr(agent, "ROGUE_AFTER", 5.0)
    assert not agent.is_rogue(now)                   # 0 seconds passed
    assert agent.is_rogue(now - 10)                  # 10 seconds passed

    monkeypatch.setattr(agent, "ROGUE_AFTER", 0.0)
    flag.write_text("x")
    assert agent.is_rogue(now)                       # the dashboard's "Simulate rogue" button
    flag.unlink()

    monkeypatch.setattr(agent, "MODE", "rogue")
    assert agent.is_rogue(now)                       # AGENT_MODE=rogue


# ── main(): which behaviour runs? ────────────────────────────────────────────
@pytest.mark.parametrize(
    "rogue_type, function",
    [
        ("loop", "rogue_loop"),
        ("token_bomb", "rogue_token_bomb"),
        ("memory_leak", "rogue_memory_leak"),
        ("paraphrase_loop", "rogue_paraphrase_loop"),
    ],
)
def test_each_rogue_type_runs_its_own_behaviour(monkeypatch, rogue_type, function):
    monkeypatch.setattr(agent, "MODE", "rogue")
    monkeypatch.setattr(agent, "ROGUE_TYPE", rogue_type)
    called = []
    for name in ROGUE_FUNCTIONS:
        monkeypatch.setattr(agent, name, recorder(called, name))
    with pytest.raises(Stop):
        agent.main()
    assert called == [function]


def test_unknown_rogue_type_falls_back_to_loop(monkeypatch, capsys):
    monkeypatch.setattr(agent, "MODE", "rogue")
    monkeypatch.setattr(agent, "ROGUE_TYPE", "abc")
    called = []
    for name in ROGUE_FUNCTIONS:
        monkeypatch.setattr(agent, name, recorder(called, name))
    with pytest.raises(Stop):
        agent.main()
    assert called == ["rogue_loop"]
    assert "unknown ROGUE_TYPE" in capsys.readouterr().out


def test_a_healthy_agent_never_runs_a_rogue_behaviour(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "MODE", "normal")
    monkeypatch.setattr(agent, "ROGUE_AFTER", 0.0)
    monkeypatch.setattr(agent, "FLAG_FILE", str(tmp_path / "go_rogue"))
    rogue_calls = []
    for name in ROGUE_FUNCTIONS:
        monkeypatch.setattr(agent, name, recorder(rogue_calls, name))
    healthy = []

    def three_healthy_calls():
        healthy.append(1)
        if len(healthy) == 3:
            raise Stop

    monkeypatch.setattr(agent, "healthy_call", three_healthy_calls)
    with pytest.raises(Stop):
        agent.main()
    assert len(healthy) == 3 and rogue_calls == []