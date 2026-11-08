"""
Acceptance tests for B1: verified auto-heal.

The judge proposes a patch. Before it is applied, the agent's recent context is replayed
against it in a **shadow dry-run**. The patch is applied automatically only if the shadow
is healthy AND the judge is confident enough. Anything else goes to the approvals inbox.

The rules under test:
  - a healthy shadow + a confident judge → the patch is applied, and the flow is logged
  - an unhealthy shadow → a proposal, and nothing is applied
  - a low confidence → a proposal, even when the shadow is healthy
  - the flag off → every patch is a proposal (the A3 behaviour, exactly)
  - the shadow never writes to the store
  - a broken shadow → a proposal, never an exception
  - the threshold is the configured one, not a constant
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from brain import service
from brain.engine import Engine
from brain.heal import Patch, validate
from brain.judge import Judge
from brain.policy import Policy
from brain.state import Snapshot
from brain.verified_heal import (HealDecision, ShadowResult, belief_is_stuck, decide, shadow_run)
from shared.config import settings
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore

# The agent's memory: the belief that keeps it looping.
STUCK_MEMORY = {"order_4471": "orders API returned 500 - retry until success"}
# The patch the judge proposes: the belief that ends the loop.
FIX_PATCH = {"memory": [{"op": "set", "key": "order_4471", "value": "cancelled - skip it and move on"}]}
# A patch that changes nothing about the belief — the agent keeps going.
USELESS_PATCH = {"memory": [{"op": "set", "key": "order_4471", "value": "orders API returned 500 - retry until success"}]}

# The prompts of a looping agent: the same request, in different words.
LOOP_PROMPTS = [
    "check order 4471 status",
    "what is the status of order 4471",
    "look up order 4471 please",
    "fetch order 4471 details",
    "order 4471 status current",
    "query order 4471 info",
    "order 4471 shipment state",
    "order 4471 delivery status",
]


@pytest.fixture
def cfg():
    """The fallback judge, with the shadow dry-run switched on."""
    return replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="",
                   verified_heal=True)


@pytest.fixture
def cfg_off():
    """The same, with the shadow dry-run switched off (the A3 behaviour)."""
    return replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="",
                   verified_heal=False)


def _snapshot(**kw) -> Snapshot:
    """A snapshot of a looping agent."""
    base = dict(agent_id="beta", tokens_per_min=1000, usd_per_min=0.01, calls_per_sec=0.5,
                total_tokens=5000, spend_usd=0.05, budget_usd=0.50, exact_repeats=9,
                loop_score=0.85, tool_cycle=True, injection_hits=0, memory_mb=10.0,
                memory_pct=20.0, calls_in_window=8)
    base.update(kw)
    return Snapshot(**base)


def _patch(raw=None) -> Patch:
    return validate(raw or FIX_PATCH, STUCK_MEMORY)


# ── the belief model ────────────────────────────────────────────────────────
def test_a_belief_that_says_retry_keeps_the_agent_going():
    assert belief_is_stuck(STUCK_MEMORY) is True


def test_a_belief_that_says_cancelled_lets_the_agent_move_on():
    assert belief_is_stuck({"order_4471": "cancelled - skip it and move on"}) is False


def test_a_belief_that_says_the_work_is_done_lets_the_agent_move_on():
    for value in ("resolved - nothing more to do", "completed", "skip it", "no longer retryable"):
        assert belief_is_stuck({"k": value}) is False, value


def test_an_empty_memory_does_not_keep_the_agent_going():
    assert belief_is_stuck({}) is False


# ── the shadow run ──────────────────────────────────────────────────────────
def test_a_healthy_shadow_says_the_agent_would_be_healthy(cfg):
    """The patch ends the belief, so the agent would do different work and look fine."""
    result = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert result.healthy is True
    assert result.verdict == "healthy"
    assert "healthy" in result.reason


def test_the_shadow_sees_the_loop_before_the_patch(cfg):
    """Before the patch the agent looks stuck — a loop rule must fire."""
    result = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert any(rule.startswith("loop_") for rule in result.rules_before), result.rules_before


def test_the_shadow_sees_no_loop_after_a_fix_that_works(cfg):
    """After the patch the agent would do different work — the loop rule is gone."""
    result = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert not any(rule.startswith("loop_") for rule in result.rules_after), result.rules_after


def test_a_shadow_that_is_still_unhealthy_says_so(cfg):
    """A patch that leaves the belief alone does not fix the agent."""
    result = shadow_run(_patch(USELESS_PATCH), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert result.healthy is False
    assert result.verdict == "still_bad"
    assert "keep retrying" in result.reason


def test_the_shadow_never_writes_to_the_store(cfg):
    """A dry-run that wrote to the database would be a heal, not a dry-run."""
    store = LocalStore(":memory:")
    store.write_memory("beta", STUCK_MEMORY, "agent", "seed")
    before = store.get_memory("beta")
    shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    after = store.get_memory("beta")
    assert after == before
    assert after["content"] == STUCK_MEMORY


def test_the_shadow_does_not_mutate_the_memory_it_was_given(cfg):
    memory = dict(STUCK_MEMORY)
    shadow_run(_patch(), memory, LOOP_PROMPTS, _snapshot(), cfg)
    assert memory == STUCK_MEMORY


def test_a_tool_policy_patch_has_no_opinion(cfg):
    """A tool override does not change the agent's prompts, so the shadow cannot predict
    them. It says so rather than guessing."""
    patch = validate({"tool_policy": {"tool": "issue_refund", "action": "deny"}}, STUCK_MEMORY)
    result = shadow_run(patch, STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert result.healthy is False
    assert result.verdict == "no_opinion"
    assert "cannot predict" in result.reason


def test_the_shadow_is_deterministic(cfg):
    """The same context, the same patch, the same answer — twice."""
    a = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    b = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert a.reason == b.reason
    assert a.rules_after == b.rules_after
    assert a.loop_score_after == b.loop_score_after


def test_a_shadow_that_cannot_apply_the_patch_has_no_opinion(cfg):
    """A patch the shadow cannot apply must not authorise anything."""
    from brain.verified_heal import ShadowResult as SR

    broken = Patch("memory_patch", ops=[{"op": "set", "key": "k"}])  # no value
    # apply_to_memory tolerates it, so the shadow runs — but a patch that is not a memory
    # patch and not a tool policy has no meaning, and must not be called healthy.
    result = shadow_run(broken, STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert result.healthy is False


# ── what "healthy" means ────────────────────────────────────────────────────
def test_a_shadow_is_healthy_when_it_fixes_the_problem_it_was_meant_to_fix(cfg):
    """
    The shadow does not ask "is this agent perfect?" — it asks "did the patch fix the
    problem the judge named?". An unrelated problem must not block a heal that works.
    """
    from brain.detectors import Finding, Level

    # The agent has TWO problems: a loop and an injection. The judge is fixing the loop.
    noisy = _snapshot(injection_hits=1, injection_score=0.9)
    finding = Finding()
    finding.add(Level.SUSPICIOUS, "loop_semantic", "the same intent repeated")
    finding.add(Level.SUSPICIOUS, "injection", "a prompt looks like an injection")

    result = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, noisy, cfg, finding=finding)

    assert result.healthy is True, result.reason
    assert "injection" in result.rules_before      # the other problem is still there
    assert "injection" in result.rules_after       # and the patch did not touch it
    assert not any(r.startswith("loop_") for r in result.rules_after)


def test_a_shadow_is_not_healthy_when_the_named_rule_still_fires(cfg):
    """The rule the judge named must be gone after the patch. If it is not, the patch failed."""
    from brain.detectors import Finding, Level

    finding = Finding()
    finding.add(Level.SUSPICIOUS, "loop_semantic", "the same intent repeated")

    # The belief still says "retry" — the patch did not touch the thing that keeps the
    # agent going, so the loop rule survives and the shadow refuses the patch.
    result = shadow_run(_patch(USELESS_PATCH), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg,
                        finding=finding)
    assert result.healthy is False, result.reason
    assert any(r.startswith("loop_") for r in result.rules_after)


def test_a_shadow_without_a_finding_assumes_the_problem_was_the_loop(cfg):
    """No finding means no named rule — the shadow falls back to the loop rules."""
    result = shadow_run(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg)
    assert result.healthy is True
    assert not any(r.startswith("loop_") for r in result.rules_after)


# ── the decision ────────────────────────────────────────────────────────────
def test_a_healthy_shadow_and_a_confident_judge_apply_the_patch(cfg):
    d = decide(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg, confidence=0.95)
    assert d.apply is True
    assert d.needs_human is False
    assert d.shadow is not None and d.shadow.healthy is True


def test_an_unhealthy_shadow_means_a_human(cfg):
    d = decide(_patch(USELESS_PATCH), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg, confidence=0.99)
    assert d.apply is False
    assert d.needs_human is True
    assert "keep retrying" in d.reason


def test_a_low_confidence_means_a_human_even_with_a_healthy_shadow(cfg):
    d = decide(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg, confidence=0.5)
    assert d.apply is False
    assert "not confident enough" in d.reason


def test_the_threshold_is_the_configured_one_not_a_constant(cfg):
    """Raise the threshold above the confidence: the same patch must now wait for a human."""
    strict = replace(cfg, autoheal_min_confidence=0.99)
    assert decide(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), strict, confidence=0.95).apply is False
    assert decide(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), strict, confidence=0.995).apply is True


def test_the_flag_off_means_every_patch_waits_for_a_human(cfg_off):
    """With the flag off the shadow is not even run — the A3 behaviour, exactly."""
    d = decide(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg_off, confidence=0.99)
    assert d.apply is False
    assert d.shadow is None
    assert "CS_VERIFIED_HEAL" in d.reason


def test_a_broken_shadow_means_a_human_not_an_exception(cfg, monkeypatch):
    """A shadow that raises must not take the tick with it, and must not authorise anything."""
    import brain.verified_heal as vh

    def boom(*_a, **_k):
        raise RuntimeError("the shadow exploded")

    monkeypatch.setattr(vh, "shadow_run", boom)
    d = vh.decide(_patch(), STUCK_MEMORY, LOOP_PROMPTS, _snapshot(), cfg, confidence=0.99)
    assert d.apply is False
    assert "the shadow run failed" in d.reason


# ── the engine wiring ───────────────────────────────────────────────────────
class _Sim:
    """Brain + fake fleet on a virtual clock."""

    def __init__(self, cfg):
        self.store = LocalStore(":memory:")
        self.policy = Policy.load("brain/policies.yaml")
        self.fleet = FakeFleet(self.store, auto_rogue=None, start=1000.0)
        self.fleet.gate = lambda a, t, args, v: service.request_tool_call(self.store, self.policy, a, t, args, v)
        self.engine = Engine(self.store, self.fleet, Judge(cfg), self.policy, cfg, sync_judge=True)
        self.now = 1000.0

    def run(self, seconds: int) -> None:
        for _ in range(seconds):
            self.now += 1
            self.fleet.step(self.now)
            self.engine.tick(self.now)


def _seed_prompts(sim, agent_id: str = "beta") -> None:
    """Give the agent some recent prompts, so the shadow has something to replay."""
    sim.engine.windows[agent_id] = sim.engine._window(agent_id)
    for i, p in enumerate(LOOP_PROMPTS):
        sim.engine.windows[agent_id].add({
            "operation": "chat", "start_ts": sim.now - 60 + i, "prompt_preview": p,
            "prompt_hash": f"h{i}", "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.001,
        })


def test_the_engine_proposes_the_patch_when_the_shadow_is_unhealthy(cfg):
    """End to end: a confident judge, a healthy shadow — but a *useless* patch. The agent
    must not get it, and the approvals inbox must get it."""
    from brain.judge import Verdict

    sim = _Sim(cfg)
    sim.store.write_memory("beta", STUCK_MEMORY, "agent", "seed")
    _seed_prompts(sim)
    v = Verdict("PAUSE", 0.99, "semantic_loop", "the belief keeps it looping", "fallback",
                patch=USELESS_PATCH)
    sim.engine._heal("beta", sim.engine._breaker("beta"), v, 1, sim.now)

    proposals = sim.store.list_heal_proposals(status="pending", agent_id="beta")
    assert proposals, "the patch must land in the approvals inbox"
    assert sim.store.get_memory("beta")["content"] == STUCK_MEMORY, "nothing may be written"
    # and the reason says why — the shadow's own words
    assert "keep retrying" in proposals[0]["reason"], proposals[0]["reason"]


def test_the_engine_applies_the_patch_when_the_shadow_is_healthy(cfg):
    """End to end: a confident judge and a patch the shadow agrees with. The memory is
    written and the agent goes back to work."""
    from brain.judge import Verdict

    sim = _Sim(cfg)
    sim.store.write_memory("beta", STUCK_MEMORY, "agent", "seed")
    v = Verdict("PAUSE", 0.99, "semantic_loop", "the belief keeps it looping", "fallback",
                patch=FIX_PATCH)
    # The engine needs the agent's recent prompts for the shadow: give it some.
    _seed_prompts(sim)
    sim.engine._heal("beta", sim.engine._breaker("beta"), v, 1, sim.now)

    memory = sim.store.get_memory("beta")
    assert memory["content"]["order_4471"] == "cancelled - skip it and move on"
    assert memory["edited_by"] == "brain:autoheal"


def test_the_engine_emits_the_shadow_flow_as_a_span(cfg):
    """The whole decision must be readable off the agent's trace: the shadow's verdict,
    the numbers and whether the patch was applied."""
    from brain.judge import Verdict

    sim = _Sim(cfg)
    events = []
    sim.engine.verdict_emitter = type("E", (), {"submit": lambda self, v: events.append(v) or True})()
    sim.store.write_memory("beta", STUCK_MEMORY, "agent", "seed")
    _seed_prompts(sim)
    v = Verdict("PAUSE", 0.99, "semantic_loop", "the belief keeps it looping", "fallback",
                patch=FIX_PATCH)
    sim.engine._heal("beta", sim.engine._breaker("beta"), v, 1, sim.now)

    shadows = [e for e in events
               if (e.get("event") or {}).get("name") == "verified_heal"]
    assert shadows, "the shadow flow must be emitted as a span"
    attrs = shadows[0]["event"]["attributes"]
    assert attrs["cloudsentinel.heal.shadow_verdict"] == "healthy"
    assert attrs["cloudsentinel.heal.applied"] is True
    assert attrs["cloudsentinel.heal.confidence"] == 0.99
    assert attrs["cloudsentinel.heal.loop_score_before"] > attrs["cloudsentinel.heal.loop_score_after"]


def test_the_engine_emits_the_shadow_flow_even_when_the_patch_is_withheld(cfg):
    """A patch that waits for a human must still be explained on the trace — the reader
    needs to know *why* it was not applied."""
    from brain.judge import Verdict

    sim = _Sim(cfg)
    events = []
    sim.engine.verdict_emitter = type("E", (), {"submit": lambda self, v: events.append(v) or True})()
    sim.store.write_memory("beta", STUCK_MEMORY, "agent", "seed")
    _seed_prompts(sim)
    v = Verdict("PAUSE", 0.99, "semantic_loop", "the belief keeps it looping", "fallback",
                patch=USELESS_PATCH)
    sim.engine._heal("beta", sim.engine._breaker("beta"), v, 1, sim.now)

    shadows = [e for e in events
               if (e.get("event") or {}).get("name") == "verified_heal"]
    assert shadows, "the shadow flow must be emitted even when the patch is withheld"
    attrs = shadows[0]["event"]["attributes"]
    assert attrs["cloudsentinel.heal.shadow_verdict"] == "still_bad"
    assert attrs["cloudsentinel.heal.applied"] is False
    assert "keep retrying" in attrs["cloudsentinel.heal.reason"]


def test_the_flow_is_logged_as_spans(cfg):
    """The whole flow must be readable off the trace: the shadow's verdict, the decision
    and the confidence."""
    from brain import verified_heal as vh

    events = []
    emitter = type("E", (), {"submit": lambda self, v: events.append(v) or True})()

    vh.emit_shadow_span(emitter, agent_id="beta", trace_id="a" * 32, parent_span_id="b" * 16,
                        shadow=ShadowResult(healthy=True, verdict="healthy",
                                            loop_score_before=0.85, loop_score_after=0.1),
                        confidence=0.95, applied=True)

    assert events, "the shadow flow must be emitted as a span"
    assert events[0]["event"]["name"] == "verified_heal"
    attrs = events[0]["event"]["attributes"]
    assert attrs["cloudsentinel.heal.shadow_verdict"] == "healthy"
    assert attrs["cloudsentinel.heal.applied"] is True
    assert attrs["cloudsentinel.heal.confidence"] == 0.95
    assert attrs["cloudsentinel.heal.loop_score_before"] == 0.85
    assert attrs["cloudsentinel.heal.loop_score_after"] == 0.1
