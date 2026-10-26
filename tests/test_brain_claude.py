"""Brain against a mocked Anthropic client: request shape, cost, and failure fallback."""
import time
from types import SimpleNamespace

import anthropic

try:  # anthropic 1.x+ is built on httpx2, older versions on httpx
    import httpx2 as httpx
except ImportError:
    import httpx

from sentinel.brain import SYSTEM_PROMPT, VERDICT_TOOL, Brain, Verdict
from sentinel.collector import Snapshot
from sentinel.detector import Finding, Level
from sentinel.engine import Sentinel
from sentinel.sources import FakeSource
from shared.config import load_settings
from shared.store import LocalStore

cfg = load_settings()
offline = cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": ""})
LOOP = Snapshot("beta", "c1", 30_000, 1.0, 5_000, 150_000, 8, 100, 20)


def finding():
    f = Finding()
    f.add(Level.SUSPICIOUS, "loop_detected", "same prompt repeated 8×")
    return f


def tool_response(action="KILL", conf=0.9, tokens_in=1_000, tokens_out=100):
    block = SimpleNamespace(type="tool_use", name="report_verdict",
                            input={"action": action, "confidence": conf, "pattern": "infinite_loop",
                                   "reason": "loop"})
    return SimpleNamespace(content=[block],
                           usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out))


class MockMessages:
    def __init__(self, result=None, error=None, delay=0.0):
        self.result, self.error, self.delay, self.calls = result, error, delay, []

    def create(self, **kw):
        self.calls.append(kw)
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def brain_with(messages):
    b = Brain(offline)
    b.client = SimpleNamespace(messages=messages)
    return b


def test_request_shape_matches_the_sdk():
    m = MockMessages(tool_response())
    v = brain_with(m).judge(LOOP, finding(), [])
    kw = m.calls[0]
    assert kw["model"] == cfg.claude_model
    assert kw["system"] == SYSTEM_PROMPT
    assert kw["tools"] == [VERDICT_TOOL]
    assert kw["tool_choice"] == {"type": "tool", "name": "report_verdict"}
    assert VERDICT_TOOL["input_schema"]["required"] == ["action", "confidence", "pattern", "reason"]
    assert kw["messages"][0]["role"] == "user" and "<agent_logs>" in kw["messages"][0]["content"]
    assert kw["max_tokens"] > 0
    assert (v.action, v.source) == ("KILL", "claude")


def test_claude_call_cost_uses_config_prices():
    priced = cfg.__class__(**{**offline.__dict__, "claude_price_in_per_mtok": 1.0,
                              "claude_price_out_per_mtok": 5.0})
    b = Brain(priced)
    b.client = SimpleNamespace(messages=MockMessages(tool_response(tokens_in=2_000, tokens_out=200)))
    v = b.judge(LOOP, finding(), [])
    assert (v.tokens_in, v.tokens_out) == (2_000, 200)
    assert abs(v.cost_usd - (2_000 * 1.0 + 200 * 5.0) / 1e6) < 1e-12


def req():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def test_api_errors_and_timeouts_fall_back():
    errors = [
        anthropic.APITimeoutError(request=req()),
        anthropic.APIConnectionError(request=req()),
        anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req()), body=None),
        anthropic.InternalServerError("boom", response=httpx.Response(500, request=req()), body=None),
        anthropic.BadRequestError("bad", response=httpx.Response(400, request=req()), body=None),
        ValueError("anything else"),
    ]
    for err in errors:
        v = brain_with(MockMessages(error=err)).judge(LOOP, finding(), [])
        assert v.source == "fallback" and "claude unavailable" in v.reason, err
        assert v.cost_usd == 0


def test_no_tool_call_falls_back_but_still_counts_cost():
    text_only = SimpleNamespace(content=[SimpleNamespace(type="text", text="hmm")],
                                usage=SimpleNamespace(input_tokens=500, output_tokens=20))
    v = brain_with(MockMessages(text_only)).judge(LOOP, finding(), [])
    assert v.source == "fallback" and v.tokens_in == 500


def test_slow_claude_does_not_block_the_loop(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None)
    s = Sentinel(source, store, brain_with(MockMessages(tool_response(), delay=1.5)), cfg)
    source.agents["beta"].rogue_since = time.time() - 15
    source.agents["beta"].next_call = time.time() - 15
    started = time.time()
    s.tick()
    s.tick()
    assert time.time() - started < 1.0         # brain is still thinking in its thread
    assert s.pending                           # …and the verdict is collected on a later tick
    next(iter(s.pending.values())).result(timeout=5)
    s.tick()
    assert not source.agents["beta"].alive


def test_engine_reports_spent_and_saved(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None)
    s = Sentinel(source, store, brain_with(MockMessages(tool_response(tokens_in=1_000, tokens_out=100))), cfg)
    source.agents["beta"].rogue_since = time.time() - 15
    source.agents["beta"].next_call = time.time() - 15
    s.tick()
    next(iter(s.pending.values())).result(timeout=5)
    s.tick()
    assert not source.agents["beta"].alive
    expected = (1_000 * cfg.claude_price_in_per_mtok + 100 * cfg.claude_price_out_per_mtok) / 1e6
    assert abs(s.brain_spent_usd - expected) < 1e-12 and s.saved_usd > 0
    costs = lambda: [a for a in store.recent_alerts() if a["rule"] == "brain_cost"]  # noqa: E731
    assert len(costs()) == 1                   # the Claude call; the kill's totals wait (60s throttle)
    s.tick(now=time.time() + cfg.brain_cost_interval_seconds + 1)   # next summary is due
    assert len(costs()) == 2
    assert any(f"saved_usd={s.saved_usd:.4f}" in a["message"] for a in costs())
    assert all(a["message"].startswith("Sentinel spent $") for a in costs())
    assert s.saved_usd > 0


def test_brain_cost_alerts_are_throttled_and_flushed_on_shutdown(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    s = Sentinel(FakeSource(cfg, auto_rogue=None), store, Brain(offline), cfg)
    n = lambda: sum(a["rule"] == "brain_cost" for a in store.recent_alerts(500))  # noqa: E731
    t0 = 1_000_000.0
    s._report_cost("beta", "first")
    for i in range(50):                        # 50 more reports within the interval → still one alert
        s._report_cost("beta", f"again {i}")
        s._flush_cost(now=t0 + i)
    assert n() == 1
    s._flush_cost(now=time.time() + 61)
    assert n() == 2
    s._report_cost("beta", "last words")
    s._flush_cost(force=True)                  # what shutdown does
    assert n() == 3


class RejectsForcedTool(MockMessages):
    def create(self, **kw):
        self.calls.append(kw)
        if kw["tool_choice"]["type"] == "tool":
            raise anthropic.BadRequestError(
                "tool_choice: type \"tool\" and \"any\" are not supported for this model.",
                response=httpx.Response(400, request=req()), body=None)
        return tool_response()


def test_model_without_forced_tool_choice_switches_to_auto():
    m = RejectsForcedTool()
    b = brain_with(m)
    v = b.judge(LOOP, finding(), [])
    assert v.source == "claude"
    assert [c["tool_choice"]["type"] for c in m.calls] == ["tool", "auto"]
    b.judge(LOOP, finding(), [])
    assert m.calls[-1]["tool_choice"] == {"type": "auto"}   # remembered, no second 400


def test_client_uses_timeout_from_settings(monkeypatch):
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    keyed = cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": "sk-test", "claude_timeout_seconds": 3.5})
    Brain(keyed)
    assert seen["timeout"] == 3.5 and seen["api_key"] == "sk-test"
