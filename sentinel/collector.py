"""
Collector: keeps a short memory of each agent's recent events and turns them into numbers.
Pure Python, no Docker, no network → very easy to unit-test.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import asdict, dataclass

from shared.contracts import AgentEvent, MetricRow

RATE_WINDOW = 15.0    # seconds used to estimate tokens/min (short = reacts fast)
CALLS_WINDOW = 5.0    # seconds used for calls/sec
LOOP_WINDOW = 60.0    # seconds used for loop detection (how often the same prompt repeats)


@dataclass
class Snapshot:
    agent: str
    container_id: str
    tokens_per_min: int
    calls_per_sec: float
    total_tokens: int
    token_budget: int
    loop_repeats: int
    memory_mb: float
    memory_pct: float

    @property
    def budget_used_pct(self) -> float:
        return 100.0 * self.total_tokens / self.token_budget if self.token_budget else 0.0

    def to_metric(self, status: str = "running") -> MetricRow:
        return MetricRow(
            agent=self.agent,
            container_id=self.container_id,
            tokens_per_min=self.tokens_per_min,
            calls_per_sec=round(self.calls_per_sec, 2),
            total_tokens=self.total_tokens,
            token_budget=self.token_budget,
            loop_repeats=self.loop_repeats,
            memory_mb=round(self.memory_mb, 1),
            memory_pct=round(self.memory_pct, 1),
            status=status,
        )

    def to_dict(self) -> dict:
        return {**asdict(self), "budget_used_pct": round(self.budget_used_pct, 1)}


class AgentState:
    """Everything the sentinel remembers about one agent."""

    def __init__(self, agent: str, container_id: str, token_budget: int):
        self.agent = agent
        self.container_id = container_id
        self.token_budget = token_budget
        self.calls: deque[AgentEvent] = deque()
        self.total_tokens = 0
        self.total_calls = 0
        self.memory_mb = 0.0
        self.memory_pct = 0.0
        self.last_brain_check = 0.0
        self.warned = False

    def add(self, event: AgentEvent) -> None:
        if event.type != "llm_call":
            return
        self.calls.append(event)
        self.total_tokens += event.tokens
        self.total_calls += 1

    def set_memory(self, memory_mb: float, memory_pct: float) -> None:
        self.memory_mb, self.memory_pct = memory_mb, memory_pct

    def _prune(self, now: float) -> None:
        while self.calls and self.calls[0].ts < now - LOOP_WINDOW:
            self.calls.popleft()

    def snapshot(self, now: float | None = None) -> Snapshot:
        now = time.time() if now is None else now
        self._prune(now)
        rate_tokens = sum(e.tokens for e in self.calls if e.ts >= now - RATE_WINDOW)
        recent_calls = sum(1 for e in self.calls if e.ts >= now - CALLS_WINDOW)
        repeats = Counter(e.prompt_hash for e in self.calls if e.prompt)
        return Snapshot(
            agent=self.agent,
            container_id=self.container_id,
            tokens_per_min=int(rate_tokens * 60 / RATE_WINDOW),
            calls_per_sec=recent_calls / CALLS_WINDOW,
            total_tokens=self.total_tokens,
            token_budget=self.token_budget,
            loop_repeats=max(repeats.values(), default=0),
            memory_mb=self.memory_mb,
            memory_pct=self.memory_pct,
        )

    def recent_events(self, n: int = 12) -> list[AgentEvent]:
        return list(self.calls)[-n:]
