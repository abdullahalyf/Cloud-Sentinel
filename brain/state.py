"""
Per-agent sliding windows: turns raw spans into numbers. Pure Python, no I/O.
"""
from __future__ import annotations

import math
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass

from brain import loops

RATE_WINDOW = 15.0    # seconds for tokens/min and $/min (short = reacts fast)
CALLS_WINDOW = 5.0    # seconds for calls/sec
LOOP_WINDOW = 60.0    # seconds kept for loop detection


def _num(value) -> float:
    """float(value), or 0.0 for None / text / NaN / inf / negative numbers."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) and v > 0 else 0.0


def _injection_score(prompts: list[str]) -> float:
    """The worst injection score among the recent prompts (A6). 0.0 when nothing fired."""
    from brain.injection import score_text

    return max((score_text(p).score for p in prompts if p), default=0.0)


@dataclass
class Snapshot:
    agent_id: str
    tokens_per_min: int
    usd_per_min: float
    calls_per_sec: float
    total_tokens: int
    spend_usd: float
    budget_usd: float
    exact_repeats: int
    loop_score: float
    tool_cycle: bool
    injection_hits: int
    memory_mb: float
    memory_pct: float
    calls_in_window: int
    # how bad the worst recent prompt scored (A6). It has a default so the many places that
    # build a Snapshot by position keep working.
    injection_score: float = 0.0

    @property
    def budget_used_pct(self) -> float:
        return 100.0 * self.spend_usd / self.budget_usd if self.budget_usd else 0.0

    def to_dict(self) -> dict:
        return {**asdict(self), "budget_used_pct": round(self.budget_used_pct, 1)}


class AgentWindow:
    """Everything the brain remembers about one agent's recent activity."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.chats: deque[dict] = deque()     # chat spans in the last LOOP_WINDOW seconds
        self.tools: deque[dict] = deque()     # execute_tool spans
        self.total_tokens = 0
        self.spend_usd = 0.0
        self.memory_mb = 0.0
        self.memory_pct = 0.0
        self.last_seen = 0.0

    def add(self, span: dict) -> None:
        """Numbers are coerced first, so one broken span (None/"abc" tokens, no timestamp) can't poison the window."""
        op = span.get("operation")
        ts = _num(span.get("start_ts"))
        if ts <= 0:  # missing/broken timestamp: treat it as "just now"
            ts = self.last_seen or time.time()
        span = {**span, "start_ts": ts, "input_tokens": int(_num(span.get("input_tokens"))),
                "output_tokens": int(_num(span.get("output_tokens"))), "cost_usd": _num(span.get("cost_usd"))}
        self.last_seen = max(self.last_seen, ts)
        self.spend_usd += span["cost_usd"]
        if op == "chat":
            self.chats.append(span)
            self.total_tokens += span["input_tokens"] + span["output_tokens"]
        elif op == "execute_tool":
            self.tools.append(span)

    def set_memory(self, mb: float, pct: float) -> None:
        self.memory_mb, self.memory_pct = mb, pct

    def reset_activity(self) -> None:
        """After a resume/restart, judge the agent on fresh behaviour only."""
        self.chats.clear()
        self.tools.clear()

    def _prune(self, now: float) -> None:
        for dq in (self.chats, self.tools):
            while dq and float(dq[0].get("start_ts") or 0) < now - LOOP_WINDOW:
                dq.popleft()

    def snapshot(self, now: float, budget_usd: float) -> Snapshot:
        self._prune(now)
        rate = [c for c in self.chats if float(c["start_ts"]) >= now - RATE_WINDOW]
        tokens = sum(int(c.get("input_tokens") or 0) + int(c.get("output_tokens") or 0) for c in rate)
        usd = sum(float(c.get("cost_usd") or 0) for c in rate)
        recent_calls = sum(1 for c in self.chats if float(c["start_ts"]) >= now - CALLS_WINDOW)
        prompts = [c.get("prompt_preview") or "" for c in self.chats]
        repeats = Counter(c.get("prompt_hash") for c in self.chats if c.get("prompt_hash"))
        tool_names = [t.get("tool_name") or "" for t in self.tools]
        recent = prompts[-12:]
        return Snapshot(
            agent_id=self.agent_id,
            tokens_per_min=int(tokens * 60 / RATE_WINDOW),
            usd_per_min=round(usd * 60 / RATE_WINDOW, 5),
            calls_per_sec=round(recent_calls / CALLS_WINDOW, 2),
            total_tokens=self.total_tokens,
            spend_usd=round(self.spend_usd, 5),
            budget_usd=budget_usd,
            exact_repeats=max(repeats.values(), default=0),
            loop_score=loops.semantic_loop_score(prompts),
            tool_cycle=loops.tool_cycle(tool_names),
            injection_hits=loops.injection_hits(recent),
            injection_score=_injection_score(recent),
            memory_mb=self.memory_mb,
            memory_pct=self.memory_pct,
            calls_in_window=len(self.chats),
        )

    def recent_prompts(self, n: int = 12) -> list[dict]:
        return [{"t": round(float(c["start_ts"]), 1), "tokens": int(c.get("input_tokens") or 0)
                 + int(c.get("output_tokens") or 0), "prompt": (c.get("prompt_preview") or "")[:200]}
                for c in list(self.chats)[-n:]]

    def recent_tools(self, n: int = 12) -> list[dict]:
        return [{"tool": t.get("tool_name"), "status": t.get("status")} for t in list(self.tools)[-n:]]
