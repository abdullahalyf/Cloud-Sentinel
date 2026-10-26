"""
Detector: fast, dumb, reliable rules. Runs every tick for every agent. No AI, no network.

  CRITICAL   → a HARD limit is broken → engine kills immediately (circuit breaker).
               This must work even if the Claude API is down or slow.
  SUSPICIOUS → a SOFT limit is broken → engine asks Claude (brain.py) to judge.
  OK         → nothing to do.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum

from sentinel.collector import Snapshot
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


def find_injection(prompts: Iterable[str], phrases: Iterable[str]) -> str:
    """First phrase from `phrases` that appears in any prompt, or ''."""
    phrases = tuple(phrases)
    for prompt in prompts:
        text = prompt.lower()
        for phrase in phrases:
            if phrase in text:
                return phrase
    return ""


def evaluate(s: Snapshot, cfg: Settings, prompts: Iterable[str] = ()) -> Finding:
    """`prompts` = the agent's recent prompts, checked for text addressed to the monitor."""
    f = Finding()

    # ── HARD limits (CRITICAL) ──
    if s.token_budget and s.total_tokens >= s.token_budget:
        f.add(Level.CRITICAL, "budget_exceeded",
              f"used {s.total_tokens:,} of {s.token_budget:,} token budget")
    if s.tokens_per_min >= cfg.hard_tokens_per_min:
        f.add(Level.CRITICAL, "token_rate_hard",
              f"{s.tokens_per_min:,} tokens/min ≥ hard limit {cfg.hard_tokens_per_min:,}")
    if s.calls_per_sec >= cfg.hard_calls_per_sec:
        f.add(Level.CRITICAL, "call_rate_hard",
              f"{s.calls_per_sec:.1f} calls/sec ≥ hard limit {cfg.hard_calls_per_sec}")
    if s.memory_pct >= cfg.hard_memory_pct:
        f.add(Level.CRITICAL, "memory_hard",
              f"memory {s.memory_pct:.0f}% ≥ hard limit {cfg.hard_memory_pct:.0f}%")

    # ── SOFT limits (SUSPICIOUS) ── only matter if nothing is critical yet
    if f.level < Level.CRITICAL:
        if s.loop_repeats >= cfg.loop_repeat_threshold:
            f.add(Level.SUSPICIOUS, "loop_detected",
                  f"same prompt repeated {s.loop_repeats}× in the last minute")
        if s.similar_repeats >= cfg.paraphrase_repeat_threshold:
            f.add(Level.SUSPICIOUS, "paraphrase_loop",
                  f"same task reworded {s.similar_repeats}× in the last 15s")
        if s.tokens_per_min >= cfg.soft_tokens_per_min:
            f.add(Level.SUSPICIOUS, "token_spike",
                  f"{s.tokens_per_min:,} tokens/min ≥ soft limit {cfg.soft_tokens_per_min:,}")
        if s.calls_per_sec >= cfg.soft_calls_per_sec:
            f.add(Level.SUSPICIOUS, "call_spike",
                  f"{s.calls_per_sec:.1f} calls/sec ≥ soft limit {cfg.soft_calls_per_sec}")
        if s.memory_pct >= cfg.soft_memory_pct:
            f.add(Level.SUSPICIOUS, "memory_high",
                  f"memory {s.memory_pct:.0f}% ≥ soft limit {cfg.soft_memory_pct:.0f}%")
        phrase = find_injection(prompts, cfg.injection_phrases)
        if phrase:
            f.add(Level.SUSPICIOUS, "prompt_injection",
                  f'prompt is addressed to the monitor ("{phrase}") — possible prompt injection')
        if s.token_budget and s.budget_used_pct >= 80:
            f.add(Level.SUSPICIOUS, "budget_80pct",
                  f"{s.budget_used_pct:.0f}% of token budget used")
    return f
