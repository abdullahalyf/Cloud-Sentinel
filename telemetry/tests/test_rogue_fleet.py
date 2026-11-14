import importlib.util
from pathlib import Path

import pytest

from shared.contracts import ROGUE_KINDS

_PATH = Path(__file__).resolve().parents[1] / "simulators" / "agent.py"
_spec = importlib.util.spec_from_file_location("sim_agent", _PATH)
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)


class _Task:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def success(self):
        pass

    def failure(self, *a):
        pass


class _Mem:
    def __init__(self):
        self.data = {}

    def get(self):
        return dict(self.data)

    def set(self, content, reason=""):
        self.data = dict(content)
        return True


class _Sim:
    def __init__(self):
        self.calls, self.prompts, self.deny = [], [], False


@pytest.fixture
def sim(monkeypatch):
    s = _Sim()
    mem = _Mem()
    s.mem = mem

    def fake_tool(name, args, fn, value_usd=None, fail_closed=False):
        s.calls.append({"name": name, "args": args, "value_usd": value_usd, "fail_closed": fail_closed})
        if s.deny:
            raise agent.cs.ToolDenied(name + " was deny")
        return fn(**args)

    monkeypatch.setattr(agent.cs, "task", lambda *a, **k: _Task())
    monkeypatch.setattr(agent.cs, "tool", fake_tool)
    monkeypatch.setattr(agent.cs, "memory", mem)
    monkeypatch.setattr(agent, "fake_llm", lambda prompt, tin, tout: s.prompts.append(prompt))
    monkeypatch.setattr(agent.time, "sleep", lambda seconds: None)
    return s


def test_every_rogue_type_the_agent_knows_is_in_the_contract():
    assert {"prompt_injection", "tool_storm", "memory_poisoning"} <= set(agent.ROGUE_TYPES)
    assert set(agent.ROGUE_TYPES) <= set(ROGUE_KINDS)


def test_prompt_injection_reads_an_injected_email_and_tries_a_big_refund(sim, capsys):
    sim.deny = True
    agent.injection_step()
    prompt = sim.prompts[0].lower()
    assert "ignore all previous instructions" in prompt or "system prompt" in prompt
    assert sim.calls == [{"name": "issue_refund", "args": {"order_id": 4471, "amount": 50000},
                          "value_usd": 410.0, "fail_closed": True}]
    assert "refund blocked" in capsys.readouterr().out


def test_prompt_injection_prints_done_when_the_gate_allows(sim, capsys):
    agent.injection_step()
    assert "refund done" in capsys.readouterr().out


def test_tool_storm_is_20_orders_api_calls_with_different_order_ids(sim):
    agent.tool_storm_step()
    assert [c["name"] for c in sim.calls] == ["orders_api"] * 20
    ids = [c["args"]["order_id"] for c in sim.calls]
    assert len(set(ids)) == 20
    assert sim.prompts == []              # no LLM between the calls


def test_tool_storm_stops_when_the_gate_denies(sim, capsys):
    sim.deny = True
    agent.tool_storm_step()
    assert len(sim.calls) == 1
    assert "orders_api blocked" in capsys.readouterr().out


def test_memory_poisoning_writes_the_false_belief_and_then_refunds_big(sim):
    agent.poison_enter()
    assert "100%" in sim.mem.data["customer_4471"]
    assert agent.poison_believed() is True
    agent.poisoning_step()
    assert sim.calls[0]["name"] == "issue_refund" and sim.calls[0]["args"]["amount"] == 50000


def test_memory_poisoning_ends_when_a_human_fixes_the_memory(sim):
    agent.poison_enter()
    sim.mem.data = {}                     # the human clears the false belief
    assert agent.poison_believed() is False


def test_slow_budget_leak_is_a_normal_looking_call_with_no_tool_and_a_new_prompt_each_time(sim):
    agent.slow_leak_step()
    agent.slow_leak_step()
    assert len(sim.prompts) == 2 and sim.calls == []
    assert "slow_budget_leak" in agent.ROGUE_TYPES


def test_slow_budget_leak_stays_under_the_soft_limits_but_ends_the_budget_in_minutes():
    per_min_tokens = (agent.LEAK_IN + agent.LEAK_OUT) * 60 / agent.LEAK_SECONDS
    per_sec_calls = 1 / agent.LEAK_SECONDS
    usd_per_min = 60 / agent.LEAK_SECONDS * (agent.LEAK_IN * 2.0 + agent.LEAK_OUT * 10.0) / 1_000_000
    assert per_min_tokens <= 0.6 * 25_000 and per_sec_calls <= 0.6 * 2.0
    assert 0.05 < usd_per_min < 0.2
    assert 0.50 / usd_per_min < 10


class _StopLoop(Exception):
    pass


@pytest.mark.parametrize("kind,step", [
    ("prompt_injection", "injection_step"),
    ("tool_storm", "tool_storm_step"),
    ("memory_poisoning", "poisoning_step"),
    ("slow_budget_leak", "slow_leak_step"),
])
def test_main_dispatches_each_new_rogue_kind_to_its_step(sim, monkeypatch, kind, step):
    hit, asked = [], [0]

    def rogue_type_now(started):
        asked[0] += 1
        if asked[0] > 3:
            raise _StopLoop
        return kind

    def fake_step():
        hit.append(kind)
        raise _StopLoop

    monkeypatch.setattr(agent.cs, "init", lambda **k: None)
    monkeypatch.setattr(agent, "rogue_type_now", rogue_type_now)
    monkeypatch.setattr(agent, step, fake_step)
    with pytest.raises(_StopLoop):
        agent.main()
    assert hit == [kind]
    if kind == "memory_poisoning":
        assert "100%" in sim.mem.data["customer_4471"]    # main() wrote the false belief first
