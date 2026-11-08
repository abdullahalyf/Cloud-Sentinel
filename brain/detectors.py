"""
Detectors: fast, deterministic rules (ARCHITECTURE §5, L0–L5). No AI, no network.

  CRITICAL   → a HARD limit is broken → breaker trips immediately (works even if Claude is down)
  SUSPICIOUS → something looks wrong  → ask the judge
  OK         → nothing to do
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from brain.state import Snapshot
from shared.config import Settings


class Level(IntEnum):
    OK = 0
    SUSPICIOUS = 1
    CRITICAL = 2


@dataclass
class Finding:
    level: Level = Level.OK
    rules: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def add(self, level: Level, rule: str, reason: str) -> None:
        self.level = max(self.level, level)
        self.rules.append(rule)
        self.reasons.append(reason)

    @property
    def text(self) -> str:
        return "; ".join(self.reasons)


def evaluate(s: Snapshot, cfg: Settings, strict: bool = False, baseline=None) -> Finding:
    """
    `strict=True` (probation) halves the soft limits.

    `baseline` (A4) is the agent's own learned normal. When it has one, the soft
    limits move with it — so a busy analyst is not stopped for being busy, and a
    quiet agent is stopped for being loud *for it*.
    """
    f = Finding()
    k = 0.5 if strict else 1.0

    # ── L0 HARD limits ── (absolute — a baseline never makes these more permissive)
    if s.budget_usd and s.spend_usd >= s.budget_usd:
        f.add(Level.CRITICAL, "budget_exceeded", f"spent ${s.spend_usd:.3f} of ${s.budget_usd:.2f} budget")
    if s.tokens_per_min >= cfg.hard_tokens_per_min:
        f.add(Level.CRITICAL, "token_rate_hard",
              f"{s.tokens_per_min:,} tokens/min ≥ hard limit {cfg.hard_tokens_per_min:,}")
    if s.calls_per_sec >= cfg.hard_calls_per_sec:
        f.add(Level.CRITICAL, "call_rate_hard", f"{s.calls_per_sec:.1f} calls/s ≥ hard limit {cfg.hard_calls_per_sec}")
    if s.memory_pct >= cfg.hard_memory_pct:
        f.add(Level.CRITICAL, "memory_hard", f"memory {s.memory_pct:.0f}% ≥ hard limit {cfg.hard_memory_pct:.0f}%")
    if f.level == Level.CRITICAL:
        return f

    # ── L1 soft limits ──
    token_limit = _adaptive(baseline, "tokens_per_min", cfg.soft_tokens_per_min)
    call_limit = _adaptive(baseline, "calls_per_sec", cfg.soft_calls_per_sec)
    if s.tokens_per_min >= token_limit * k:
        f.add(Level.SUSPICIOUS, "token_spike", _reason(s.tokens_per_min, baseline, "tokens_per_min",
                                                      f"{s.tokens_per_min:,} tokens/min ≥ soft limit"))
    if s.calls_per_sec >= call_limit * k:
        f.add(Level.SUSPICIOUS, "call_spike", _reason(s.calls_per_sec, baseline, "calls_per_sec",
                                                      f"{s.calls_per_sec:.1f} calls/s ≥ soft limit"))
    if s.memory_pct >= cfg.soft_memory_pct:
        f.add(Level.SUSPICIOUS, "memory_high", f"memory {s.memory_pct:.0f}% ≥ soft limit {cfg.soft_memory_pct:.0f}%")
    if s.budget_usd and s.budget_used_pct >= 80:
        f.add(Level.SUSPICIOUS, "budget_80pct", f"{s.budget_used_pct:.0f}% of budget used")
    # ── L2 exact loop ──
    if s.exact_repeats >= cfg.loop_repeat_threshold * k:
        f.add(Level.SUSPICIOUS, "loop_exact", f"same prompt repeated {s.exact_repeats}× in the last minute")
    # ── L3 semantic loop ──
    if s.loop_score >= cfg.loop_score_threshold and s.exact_repeats < cfg.loop_repeat_threshold:
        f.add(Level.SUSPICIOUS, "loop_semantic",
              f"semantic loop score {s.loop_score:.2f}: different words, same intent")
    # ── L4 tool cycle ──
    if s.tool_cycle and (s.loop_score >= 0.5 or s.exact_repeats >= 4):
        f.add(Level.SUSPICIOUS, "tool_cycle", "tool calls repeat the same short pattern")
    # ── L5 prompt injection aimed at the monitor ──
    if s.injection_hits:
        f.add(Level.SUSPICIOUS, "injection", f"{s.injection_hits} prompt(s) contain text addressed to the monitor")
    return f


def _adaptive(baseline, metric: str, fixed_soft: float) -> float:
    """The soft limit for a metric: the agent's own limit when it has one, else the fixed one."""
    if baseline is None:
        return fixed_soft
    limit = baseline.limit(metric)
    return limit if limit is not None else fixed_soft


def _reason(value: float, baseline, metric: str, fallback: str) -> str:
    """The finding text says how far above its own normal the agent is (A4)."""
    if baseline is None:
        return fallback
    from brain.baseline import describe

    extra = describe(value, baseline.metrics.get(metric), metric)
    return f"{fallback} — {extra}" if extra else fallback
