"""
Verified auto-heal: prove the patch works before it touches the agent.   Owner: Alif.

**The problem.** A3 applies a judge's memory patch the moment the judge is confident. But
confidence is the judge's *opinion*, and the only evidence that the patch worked is whether
the agent trips again on probation — which is a bet, and a bet the operator pays for in
burned money while the agent loops a second time.

**The idea.** Before applying the patch, **replay the agent's recent context against the
patch in a shadow dry-run**. Take the agent's recent prompts and its memory, apply the patch
to a *copy*, and ask the detectors what the patched agent would look like. If the patched
copy is healthy, the patch works and may be applied. If the patched copy still looks bad,
the patch does not fix the problem — applying it would only make the agent confidently
broken, so it goes to the approvals inbox instead.

**The shadow never touches the store.** It works on copies. A dry-run that wrote to the
database would be a heal, not a dry-run.

**What "the patched agent" means.** An agent's *behaviour* comes from two things: what it
sends (the prompts) and what it believes (the memory). A memory patch changes the second,
and the second changes the first — a belief of "retry until success" is what makes the
agent send the same request again. So the shadow does not re-score the old prompts against
the new memory (that would change nothing, and every patch would "pass"). It models the
*next* prompts the agent would send with the new belief, and scores those.

The model is deliberately simple and deterministic:

- The belief is judged by what it **says**. A belief that still talks about retrying, or
  waiting, or trying again is a belief that keeps the agent going — the shadow keeps the
  agent's old (repeating) prompts, so the agent still looks bad.
- A belief that says the work is finished, cancelled, done, resolved — or that simply no
  longer mentions retrying — lets the agent move on. The shadow then assumes the agent
  sends *varied* prompts (the agent is doing different work), and the loop score collapses.

This is a model, not a simulation. It is honest about that: the shadow says "with this
belief, would the agent still be stuck?", and the answer is a **model-based** guess, not a
proof. That is why the rule is *both* conditions — a healthy shadow **and** a confident
judge — and why anything else goes to a human. The shadow can only ever *stop* an
automatic action; it can never authorise one on its own.

**The flag.** `CS_VERIFIED_HEAL` (off by default until it is fully tested). With the flag
off, every patch is a proposal for a human — the A3 behaviour, exactly.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from brain.detectors import Finding, Level, evaluate
from brain.heal import Patch, apply_to_memory
from brain.state import Snapshot

log = logging.getLogger("brain.verified_heal")


# ── what a belief says ──────────────────────────────────────────────────────
# These are the words that mean "keep going". A belief that still contains one of them
# is a belief the agent will obey, so the agent is still stuck.
_STUCK_WORDS = (
    "retry", "retries", "retrying", "try again", "try again later",
    "keep trying", "wait and retry", "pending", "in progress", "not yet",
    "until success", "until it works", "again later", "come back to",
)

# These are the words that mean "the work is over, move on". A belief that contains one
# of them lets the agent do different work next.
_DONE_WORDS = (
    "cancelled", "canceled", "cancel", "skip", "skip it", "move on", "done",
    "resolved", "closed", "completed", "complete", "finished", "abandoned",
    "give up", "stop retrying", "no longer", "do not retry", "don't retry",
    "not retry", "escalate to", "hand off",
)


def _text(value) -> str:
    return str(value or "").lower()


def belief_is_stuck(memory: dict) -> bool:
    """
    Does this memory still tell the agent to keep going?

    A memory that says "the orders API returned 500 - retry until success" is a belief
    the agent obeys: it retries, it loops, it burns money. A memory that says "cancelled -
    skip it and move on" is a belief that ends the loop.
    """
    blob = _text(" ".join(f"{k} {v}" for k, v in (memory or {}).items()))
    if any(word in blob for word in _DONE_WORDS):
        return False
    return any(word in blob for word in _STUCK_WORDS)


def _varied_prompts(prompts: list[str], count: int = 8) -> list[str]:
    """
    The prompts the agent would send next if its belief let it move on.

    The agent is doing *different* work, so the prompts differ from each other. They are
    built from the agent's own recent prompts (so they stay in the agent's voice) but each
    one gets a different work id, which is what makes the loop detector see new work —
    the loop detector treats prompts about different ids as different work.
    """
    base = [p for p in (prompts or []) if p]
    if not base:
        return []
    out: list[str] = []
    for i in range(count):
        template = base[i % len(base)]
        # A different id per prompt: "check order 4471" -> "check order 9107".
        out.append(re.sub(r"\d{3,}", lambda m: str(9100 + i * 7 + int(m.group()) % 90), template))
    return out


# ── the result ──────────────────────────────────────────────────────────────
@dataclass
class ShadowResult:
    """What the shadow run decided, and why."""

    healthy: bool = False
    reason: str = ""
    rules_before: list[str] = field(default_factory=list)
    rules_after: list[str] = field(default_factory=list)
    loop_score_before: float = 0.0
    loop_score_after: float = 0.0
    patched_memory: dict = field(default_factory=dict)
    verdict: str = ""          # "healthy" | "still_bad" | "no_opinion"

    @property
    def fixed(self) -> bool:
        """Did the patch change the picture at all?"""
        return set(self.rules_before) != set(self.rules_after) or \
            self.loop_score_after < self.loop_score_before


def shadow_run(patch: Patch, memory: Optional[dict], prompts: list[str], snapshot: Snapshot,
               cfg, finding: Optional[Finding] = None, baseline=None) -> ShadowResult:
    """
    Replay the agent's recent context against the patch, without changing anything.

    Returns a `ShadowResult`. It never raises: a shadow that cannot decide must not take
    the tick with it, and a shadow that cannot decide must not authorise an automatic
    action either — the caller treats "no opinion" as "ask a human".
    """
    memory = dict(memory or {})
    try:
        patched = apply_to_memory(memory, patch)
    except Exception as exc:
        log.warning("the shadow could not apply the patch: %s", exc)
        return ShadowResult(healthy=False, reason=f"the shadow could not apply the patch: {exc}",
                            verdict="no_opinion")

    if snapshot is None:
        # The brain has no window for this agent, so it cannot say what the agent would
        # look like after the patch. No opinion means a human.
        return ShadowResult(healthy=False,
                            reason="the shadow has no snapshot of the agent to replay",
                            patched_memory=patched, verdict="no_opinion")

    # What the agent looked like *before* the patch. The same detectors, the same snapshot.
    before = evaluate(snapshot, cfg, baseline=baseline)
    if patch.kind == "tool_policy":
        # A tool override does not change the agent's belief — it removes one tool from
        # its hands. The shadow can say the tool is gone, but it cannot say the agent's
        # *prompts* would change, so it has no opinion about the loop. It says the tool
        # is restricted, which is what the patch does, and leaves the loop to the judge.
        return ShadowResult(
            healthy=False,
            reason=(f"the patch restricts the tool {patch.tool!r}; the shadow cannot predict "
                    "the agent's prompts afterwards"),
            rules_before=list(before.rules),
            rules_after=list(before.rules),
            loop_score_before=float(snapshot.loop_score),
            loop_score_after=float(snapshot.loop_score),
            patched_memory=patched,
            verdict="no_opinion",
        )

    # The belief after the patch. Still "keep going"? Then the agent still loops.
    if belief_is_stuck(patched):
        return ShadowResult(
            healthy=False,
            reason=("after the patch the agent's memory still tells it to keep retrying, "
                    "so it would keep looping"),
            rules_before=list(before.rules),
            rules_after=list(before.rules),
            loop_score_before=float(snapshot.loop_score),
            loop_score_after=float(snapshot.loop_score),
            patched_memory=patched,
            verdict="still_bad",
        )

    # The belief lets the agent move on. Model the prompts it would send next.
    from brain.loops import semantic_loop_score

    old_prompts = [p for p in (prompts or []) if p]
    new_prompts = _varied_prompts(old_prompts)
    loop_before = semantic_loop_score(old_prompts)
    loop_after = semantic_loop_score(new_prompts)

    # The snapshot the detectors would see, if the agent moved on.
    shadow_snapshot = _shadow_snapshot(snapshot, loop_after)
    after = evaluate(shadow_snapshot, cfg, baseline=baseline)

    # **What "healthy" means.** The shadow does not ask "is this agent perfect?" — an agent
    # with a prompt-injection problem is not perfect, and no belief patch will make it so.
    # It asks the only question that matters: *did the patch fix the problem it was meant to
    # fix?* The rules the judge named are the ones the patch is supposed to silence, so the
    # shadow is healthy when those rules are gone and no *new* rule appeared.
    #
    # Without a finding the shadow assumes the problem was the loop — that is the only thing
    # a memory belief can fix.
    target = _target_rules(finding, before)
    still_firing = [r for r in target if r in after.rules]
    new_rules = [r for r in after.rules if r not in before.rules]

    healthy = not still_firing and not new_rules
    reason = _why(healthy, before, after, loop_before, loop_after, still_firing, new_rules, target)
    return ShadowResult(
        healthy=healthy,
        reason=reason,
        rules_before=list(before.rules),
        rules_after=list(after.rules),
        loop_score_before=loop_before,
        loop_score_after=loop_after,
        patched_memory=patched,
        verdict="healthy" if healthy else "still_bad",
    )


# The rules a belief patch can plausibly fix. A memory patch changes what the agent *believes*,
# so it can end a loop — it cannot fix a token rate, a memory footprint or an injection.
_LOOP_RULES = ("loop_semantic", "loop_exact", "tool_cycle")


def _target_rules(finding: Optional[Finding], before: Finding) -> list[str]:
    """
    The rules the patch is supposed to silence.

    The judge named them in the finding it saw, so they are the rules the patch was written
    against. When there is no finding, the shadow assumes the problem was the loop — the only
    thing a memory belief can fix.
    """
    if finding is not None and finding.rules:
        named = [r for r in finding.rules if r in _LOOP_RULES]
        if named:
            return named
    firing = [r for r in before.rules if r in _LOOP_RULES]
    return firing or list(_LOOP_RULES)


def _shadow_snapshot(snapshot: Snapshot, loop_score: float) -> Snapshot:
    """The snapshot the agent would have, if its new belief let it do different work.

    Only the loop-shaped numbers change: the loop score, the exact repeat count and the
    tool cycle (the agent is no longer repeating the same call). The rate numbers stay
    what they were — the patch does not change how fast the agent talks.
    """
    return Snapshot(
        agent_id=snapshot.agent_id,
        tokens_per_min=snapshot.tokens_per_min,
        usd_per_min=snapshot.usd_per_min,
        calls_per_sec=snapshot.calls_per_sec,
        total_tokens=snapshot.total_tokens,
        spend_usd=snapshot.spend_usd,
        budget_usd=snapshot.budget_usd,
        exact_repeats=0 if loop_score < snapshot.loop_score else snapshot.exact_repeats,
        loop_score=loop_score,
        tool_cycle=False if loop_score < snapshot.loop_score else snapshot.tool_cycle,
        injection_hits=snapshot.injection_hits,
        memory_mb=snapshot.memory_mb,
        memory_pct=snapshot.memory_pct,
        calls_in_window=snapshot.calls_in_window,
        injection_score=snapshot.injection_score,
    )


def _why(healthy: bool, before: Finding, after: Finding, loop_before: float, loop_after: float,
         still_firing: list[str], new_rules: list[str], target: list[str]) -> str:
    if healthy:
        return (f"the shadow is healthy: with the patched belief the loop score falls from "
                f"{loop_before:.2f} to {loop_after:.2f} and "
                f"{', '.join(target) or 'the loop rules'} no longer fire "
                f"(before: {', '.join(before.rules) or 'nothing'})")
    if still_firing:
        return (f"the shadow is still unhealthy: with the patched belief "
                f"{', '.join(still_firing)} still fire (loop score {loop_after:.2f})")
    return (f"the shadow is still unhealthy: the patched belief fixes the loop, but "
            f"{', '.join(new_rules)} would start firing")


# ── the decision ────────────────────────────────────────────────────────────
@dataclass
class HealDecision:
    """The whole decision, in one place: apply it, or ask a human."""

    apply: bool = False
    reason: str = ""
    shadow: Optional[ShadowResult] = None
    confidence: float = 0.0

    @property
    def needs_human(self) -> bool:
        return not self.apply


def decide(patch: Patch, memory: Optional[dict], prompts: list[str], snapshot: Snapshot, cfg,
           confidence: float, finding: Optional[Finding] = None, baseline=None) -> HealDecision:
    """
    May this patch be applied automatically?

    **Both** conditions must hold:

    1. the judge is confident enough (at least `cfg.autoheal_min_confidence`), and
    2. the shadow run is healthy — the patched agent would not still look bad.

    The shadow can only ever *veto*. A healthy shadow on its own never authorises an
    automatic action: the confidence is what says the judge understood the problem, and
    the shadow is what says the patch fixes it. Either one missing means a human.
    """
    if not getattr(cfg, "verified_heal", False):
        # The flag is off: the shadow is not run at all, and every patch is a proposal.
        return HealDecision(apply=False, reason="verified auto-heal is off (CS_VERIFIED_HEAL)",
                            confidence=confidence)

    try:
        shadow = shadow_run(patch, memory, prompts, snapshot, cfg, finding=finding, baseline=baseline)
    except Exception as exc:
        # A shadow that cannot decide must not authorise anything.
        log.warning("the shadow run failed: %s", exc)
        return HealDecision(apply=False, reason=f"the shadow run failed: {exc}",
                            confidence=confidence)

    if not shadow.healthy:
        return HealDecision(apply=False, reason=shadow.reason or "the shadow was not healthy",
                            shadow=shadow, confidence=confidence)
    if float(confidence) < float(cfg.autoheal_min_confidence):
        return HealDecision(apply=False,
                            reason=(f"the judge is not confident enough "
                                    f"({confidence:.2f} < {cfg.autoheal_min_confidence:.2f})"),
                            shadow=shadow, confidence=confidence)
    return HealDecision(apply=True, reason=shadow.reason, shadow=shadow, confidence=confidence)


# ── the flow on the trace ───────────────────────────────────────────────────
# The whole decision — the shadow's verdict, the numbers behind it and whether the patch
# was applied — goes onto the agent's own OpenTelemetry trace, as a span event next to
# the behaviour that caused it. A decision nobody can read is a decision nobody can trust.
SHADOW_EVENT_NAME = "verified_heal"


def shadow_span(agent_id: str, trace_id: str, parent_span_id: str, shadow: ShadowResult,
                confidence: float, applied: bool, reason: str = "") -> dict:
    """The shadow flow, as the plain data the emitter needs. No I/O, so it is testable."""
    from shared.contracts import Attr

    attributes = {
        Attr.CS_AGENT_ID: agent_id,
        Attr.CS_HEAL_SHADOW_VERDICT: str(shadow.verdict or ""),
        Attr.CS_HEAL_APPLIED: bool(applied),
        Attr.CS_HEAL_CONFIDENCE: round(float(confidence or 0.0), 4),
        Attr.CS_HEAL_LOOP_SCORE_BEFORE: round(float(shadow.loop_score_before or 0.0), 4),
        Attr.CS_HEAL_LOOP_SCORE_AFTER: round(float(shadow.loop_score_after or 0.0), 4),
        Attr.CS_HEAL_REASON: str(reason or "")[:300],
    }
    return {
        "agent_id": agent_id,
        "operation": "cs_verdict",
        "name": f"cs_verdict {agent_id}",
        "trace_id": (trace_id or "").strip().lower(),
        "parent_span_id": (parent_span_id or "").strip().lower(),
        "event": {"name": SHADOW_EVENT_NAME, "attributes": attributes},
        "attributes": attributes,
    }


def emit_shadow_span(sender: Any, agent_id: str, trace_id: str, parent_span_id: str,
                     shadow: ShadowResult, confidence: float, applied: bool,
                     reason: str = "") -> bool:
    """Emit the shadow flow through `sender` (anything with a `submit(verdict)`).

    Never raises: a lost span is a nuisance, a lost tick is an outage.
    """
    if sender is None:
        return False
    try:
        span = shadow_span(agent_id, trace_id, parent_span_id, shadow, confidence, applied, reason)
        return bool(sender.submit(span))
    except Exception as exc:
        log.warning("could not send the shadow-heal span: %s", exc)
        return False


__all__ = ["ShadowResult", "HealDecision", "shadow_run", "decide", "belief_is_stuck",
           "emit_shadow_span", "shadow_span", "SHADOW_EVENT_NAME"]
