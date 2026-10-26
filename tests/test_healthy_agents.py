"""Healthy agents must never be flagged or killed: 3 simulated minutes per style, 2 calls/s, fallback brain.
(scripts/healthy_agents.py does the same in real time with real processes.)"""
import importlib.util
import random
from dataclasses import replace
from pathlib import Path

import pytest

from sentinel.brain import Brain
from sentinel.collector import AgentState
from sentinel.detector import Level, evaluate
from shared.config import load_settings
from shared.contracts import AgentEvent

ROOT = Path(__file__).resolve().parent.parent
cfg = replace(load_settings(), anthropic_api_key="", gemini_api_key="")


def healthy_module(style):
    spec = importlib.util.spec_from_file_location("healthy_agent", ROOT / "scripts" / "healthy_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STYLE = style
    return mod


def simulate(style, seconds=180, rate=2.0, seed=1):
    """Feed one agent's calls to the detector + brain like the engine does (brain at most every 10s).
    → (worst finding level, verdict actions)"""
    random.seed(seed)
    gen = healthy_module(style).prompts()
    st, brain, actions, worst, last_check = AgentState("h", "c", 10**9), Brain(cfg), [], Level.OK, -99.0
    t = 0.0
    while t < seconds:
        t += random.uniform(0.7, 1.3) / rate
        st.add(AgentEvent("h", "llm_call", 1000 + t, tokens_in=random.randint(100, 160),
                          tokens_out=random.randint(40, 90), model="m", prompt=next(gen)))
        snap = st.snapshot(1000 + t)   # evaluated at every call: stricter than once a second
        finding = evaluate(snap, cfg, [e.prompt for e in st.calls])
        worst = max(worst, finding.level)
        if finding.level == Level.SUSPICIOUS and t - last_check >= cfg.brain_cooldown_seconds:
            last_check = t
            actions.append(brain.judge(snap, finding, st.recent_events(), now=1000 + t).action)

    return worst, actions


@pytest.mark.parametrize("style", ["names", "year", "jobs"])
@pytest.mark.parametrize("seed", [1, 2])
def test_healthy_agent_is_never_flagged_or_killed(style, seed):
    worst, actions = simulate(style, seed=seed)
    assert worst == Level.OK and "KILL" not in actions, (style, worst, actions)
