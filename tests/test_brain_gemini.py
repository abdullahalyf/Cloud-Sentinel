"""Gemini provider with a mocked google-genai client. No network, no key."""
from dataclasses import replace
from types import SimpleNamespace

from sentinel.brain import Brain
from sentinel.collector import AgentState
from sentinel.detector import evaluate
from shared.config import load_settings
from shared.contracts import AgentEvent

cfg = replace(load_settings(), brain_provider="gemini", gemini_api_key="g-test", anthropic_api_key="")


class FakeModels:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        usage = SimpleNamespace(prompt_token_count=1_000, candidates_token_count=50)
        return SimpleNamespace(text=self.text, usage_metadata=usage)


def gemini_brain(models: FakeModels) -> Brain:
    brain = Brain(replace(cfg, gemini_api_key=""))  # no real client
    brain.gemini = SimpleNamespace(models=models)
    return brain


def looping():
    st = AgentState("beta", "c1", 150_000)
    for i in range(10):
        st.add(AgentEvent("beta", "llm_call", 1000.0 + i, tokens_in=300, tokens_out=100, model="m",
                          prompt="Summarise ticket #4471"))
    snap = st.snapshot(1010.0)
    return snap, evaluate(snap, cfg, [e.prompt for e in st.calls]), st.recent_events(12)


def test_gemini_json_becomes_a_verdict_with_cost():
    models = FakeModels('{"action": "KILL", "confidence": 0.9, "pattern": "infinite_loop", "reason": "loop"}')
    snap, finding, recent = looping()
    v = gemini_brain(models).judge(snap, finding, recent, cfg)
    assert (v.action, v.source, v.pattern) == ("KILL", "gemini", "infinite_loop")
    assert v.tokens_in == 1_000 and v.cost_usd > 0
    assert models.calls[0]["model"] == cfg.gemini_model


def test_gemini_error_or_bad_json_falls_back():
    snap, finding, recent = looping()
    for models in (FakeModels(error=TimeoutError("slow")), FakeModels("not json"), FakeModels("[1, 2]")):
        v = gemini_brain(models).judge(snap, finding, recent, cfg)
        assert v.source == "fallback" and "gemini unavailable" in v.reason


def test_provider_selection():
    assert cfg.use_gemini and not cfg.use_claude and cfg.brain_name.startswith("Gemini")
    claude = replace(cfg, brain_provider="claude", anthropic_api_key="sk")
    assert claude.use_claude and not claude.use_gemini
    assert Brain(replace(cfg, gemini_api_key="")).gemini is None   # no key → fallback


def test_example_env_has_no_secrets_and_safe_hard_limits():
    from pathlib import Path

    env = dict(line.split("=", 1) for line in
               (Path(__file__).resolve().parent.parent / ".env.example").read_text().splitlines()
               if "=" in line and not line.startswith("#"))
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "SUPABASE_KEY", "WEBHOOK_URL"):
        assert env.get(key, "").strip() == "", key
    assert env["HARD_TOKENS_PER_MIN"].strip() == "60000" and env["HARD_CALLS_PER_SEC"].strip() == "8"


def test_cost_alert_names_the_provider_and_model_that_answered(tmp_path):
    from sentinel.engine import Sentinel
    from sentinel.sources import FakeSource
    from shared.store import LocalStore

    store = LocalStore(str(tmp_path / "t.db"))
    models = FakeModels('{"action": "WARN", "confidence": 0.5, "pattern": "other", "reason": "hmm"}')
    source = FakeSource(cfg, auto_rogue=None)
    s = Sentinel(source, store, gemini_brain(models), cfg)
    source.agents["beta"].rogue_since = source.agents["beta"].next_call = __import__("time").time() - 15
    s.tick()
    next(iter(s.pending.values())).result(timeout=5)
    s.tick()
    costs = [a["message"] for a in store.recent_alerts() if a["rule"] == "brain_cost"]
    assert any(f"gemini call 1,000 in + 50 out tokens" in m and cfg.gemini_model in m for m in costs), costs
    assert not any("claude call" in m for m in costs)
