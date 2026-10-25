"""Brain memory: past verdicts reach Claude's message; fallback escalates a 2nd WARN to KILL."""
from sentinel.brain import Brain, Verdict, build_user_message, fallback_verdict
from sentinel.collector import Snapshot
from sentinel.detector import Finding, Level
from shared.config import load_settings

cfg = load_settings()
NOW = 1_000_000.0
WARN = Verdict("WARN", 0.6, "infinite_loop", "odd but maybe fine", "claude")


def spiky_snapshot(agent="beta"):
    # token spike only, no loop → the fallback alone would say WARN
    return Snapshot(agent, "c1", cfg.soft_tokens_per_min + 1, 0.5, 1000, 150_000, 1, 80.0, 15.0)


def spike_finding():
    f = Finding()
    f.add(Level.SUSPICIOUS, "token_spike", "tokens/min above soft limit")
    return f


def test_first_warn_stays_warn():
    v = fallback_verdict(spiky_snapshot(), spike_finding(), cfg, now=NOW)
    assert v.action == "WARN"


def test_second_warn_within_60s_becomes_kill():
    v = fallback_verdict(spiky_snapshot(), spike_finding(), cfg, past=[(NOW - 12, WARN)], now=NOW)
    assert v.action == "KILL" and v.confidence >= cfg.brain_kill_confidence


def test_old_warn_does_not_escalate():
    v = fallback_verdict(spiky_snapshot(), spike_finding(), cfg, past=[(NOW - 61, WARN)], now=NOW)
    assert v.action == "WARN"


def test_user_message_lists_previous_verdicts():
    msg = build_user_message(spiky_snapshot(), spike_finding(), [], cfg, past=[(NOW - 12, WARN)], now=NOW)
    assert "WARN 60% infinite_loop, 12s ago" in msg
    assert "none" in build_user_message(spiky_snapshot(), spike_finding(), [], cfg, now=NOW)


def test_brain_keeps_last_3_verdicts_per_agent():
    brain = Brain(cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": ""}))  # fallback mode
    actions = [brain.judge(spiky_snapshot(), spike_finding(), []).action for _ in range(5)]
    assert actions == ["WARN", "KILL", "KILL", "KILL", "KILL"]
    assert len(brain.history["beta"]) == 3
    assert brain.judge(spiky_snapshot("gamma"), spike_finding(), []).action == "WARN"  # per agent
