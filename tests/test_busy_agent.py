"""A genuinely busy healthy agent (~52k tokens/min, varied prompts) must not be killed by the fallback."""
from sentinel.brain import Brain, fallback_verdict
from sentinel.collector import AgentState, Snapshot
from sentinel.detector import Level, evaluate
from shared.config import load_settings
from shared.contracts import AgentEvent

cfg = load_settings()
HALFWAY = (cfg.soft_tokens_per_min + cfg.hard_tokens_per_min) / 2   # 52,500


def snap(tokens, repeats=1, calls=1.5, mem=25.0):
    return Snapshot("alpha", "c", tokens, calls, 10_000, 150_000, repeats, 128.0, mem)


def verdict(s, past=(), now=1000.0):
    finding = evaluate(s, cfg)
    assert finding.level == Level.SUSPICIOUS, finding.reasons
    return fallback_verdict(s, finding, cfg, past=past, now=now)


def test_52k_tokens_with_varied_prompts_and_no_other_signal_only_warns():
    v = verdict(snap(52_600))
    assert HALFWAY < 52_600 < cfg.hard_tokens_per_min
    assert v.action == "WARN"


def test_a_real_agent_stream_at_52k_tokens_per_min_survives_the_whole_minute():
    brain = Brain(cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": "", "gemini_api_key": ""}))
    st = AgentState("alpha", "c", 10**9)
    verdicts = []
    for i in range(240):                      # 2 calls/s for 2 minutes, 434 tokens each ≈ 52k/min, every prompt new
        ts = 1000 + i * 0.5
        st.add(AgentEvent("alpha", "llm_call", ts, tokens_in=300, tokens_out=134, model="m",
                          prompt=f"Classify invoice line item #{5000 + 7 * i} ({['hosting', 'chairs', 'lunch'][i % 3]})"))
        st.set_memory(128.0, 25.0, now=ts)
        if i >= 40 and i % 20 == 19:          # warmed up; a brain check about every 10s
            s = st.snapshot(ts)
            finding = evaluate(s, cfg)
            if finding.level == Level.SUSPICIOUS:
                verdicts.append(brain.judge(s, finding, [], cfg, now=ts))
    assert len(verdicts) >= 5 and {v.action for v in verdicts} == {"WARN"}, [(v.action, v.reason) for v in verdicts]


def test_high_spend_with_a_second_signal_is_still_killed():
    assert verdict(snap(52_600, repeats=4)).action == "KILL"            # the same prompt keeps coming back
    assert verdict(snap(52_600, calls=6.0)).action == "KILL"            # a call rate far above normal
    assert verdict(snap(52_600, mem=72.0)).action == "KILL"             # memory past its soft limit
    # the fallback kills at the hard limit too (the rules normally do it first, before the brain is asked)
    finding = evaluate(snap(65_000), cfg)
    assert finding.level == Level.CRITICAL and fallback_verdict(snap(65_000), finding, cfg).action == "KILL"


def test_spend_that_keeps_rising_after_the_warning_is_killed():
    first = verdict(snap(46_000))
    assert first.action == "WARN"
    first.evidence = (1, 46_000, 25.0)
    assert verdict(snap(52_600), past=[(990.0, first)]).action == "WARN"   # +14% is noise
    assert verdict(snap(58_000), past=[(990.0, first)]).action == "KILL"   # +26% is a real climb
