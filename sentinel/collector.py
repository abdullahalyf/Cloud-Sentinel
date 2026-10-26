"""
Collector: keeps a short memory of each agent's recent events and turns them into numbers.
Pure Python, no Docker, no network → very easy to unit-test.
"""
from __future__ import annotations

import re
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass

from shared.contracts import AgentEvent, MetricRow

RATE_WINDOW = 15.0    # seconds used to estimate tokens/min (short = reacts fast)
CALLS_WINDOW = 5.0    # seconds used for calls/sec
LOOP_WINDOW = 60.0    # seconds used for loop detection (how often the same prompt repeats)
SIMILAR_WINDOW = 15.0   # seconds used for paraphrase detection (same task, new wording)

STOPWORDS = frozenset("""a an and the of to for on in at by with from as is are was be it its this that these those
or if then so up out off over again also please try retry once more still need what where which who how me my
you your i we us our can could would should will just yet back short answer result report tell find info""".split())
NUMBER = re.compile(r"\d+")
WORD = re.compile(r"[a-z][a-z']+")


def signature(prompt: str) -> tuple[frozenset[str], frozenset[str]]:
    """(numbers, content words) of a prompt. 'order #4471' and 'Order 4471!' share a signature part;
    words are lowercased, stopwords dropped and a plural 's' removed."""
    text = prompt.lower()
    words = {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in WORD.findall(text)} - STOPWORDS
    return frozenset(NUMBER.findall(text)), frozenset(words)


def similar(a: tuple[frozenset[str], frozenset[str]], b: tuple[frozenset[str], frozenset[str]]) -> bool:
    """Same job, other words? Prompts about different ids (job 17 vs job 18) never match: different work.
    Same numbers + at least a third of the shorter word list shared (no numbers: 70%)."""
    (nums_a, words_a), (nums_b, words_b) = a, b
    if nums_a != nums_b or not words_a or not words_b:
        return False
    shared = len(words_a & words_b)
    return shared / min(len(words_a), len(words_b)) >= (0.3 if nums_a else 0.7) and shared > 0


def biggest_cluster(signatures: list[tuple[frozenset[str], frozenset[str]]]) -> int:
    """Size of the largest group of mutually-chained similar prompts (single link)."""
    seen: set[int] = set()
    best = 0
    for i in range(len(signatures)):
        if i in seen:
            continue
        seen.add(i)
        stack, size = [i], 0
        while stack:
            cur = stack.pop()
            size += 1
            for j in range(len(signatures)):
                if j not in seen and similar(signatures[cur], signatures[j]):
                    seen.add(j)
                    stack.append(j)
        best = max(best, size)
    return best


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
    similar_repeats: int = 0   # largest group of reworded versions of one prompt (last 15s)

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
            loop_repeats=max(self.loop_repeats, self.similar_repeats),
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
        self._signatures: deque = deque()   # signature(prompt) for each entry of `calls`
        self.total_tokens = 0
        self.total_calls = 0
        self.memory_mb = 0.0
        self.memory_pct = 0.0
        self.last_brain_check = 0.0
        self.last_brain_rules: frozenset[str] = frozenset()  # rules the brain was last asked about
        self.warned = False

    def add(self, event: AgentEvent) -> None:
        if event.type != "llm_call":
            return
        self.calls.append(event)
        self._signatures.append(signature(event.prompt) if event.prompt else None)
        self.total_tokens += event.tokens
        self.total_calls += 1

    def set_memory(self, memory_mb: float, memory_pct: float) -> None:
        self.memory_mb, self.memory_pct = memory_mb, memory_pct

    def _prune(self, now: float) -> None:
        while self.calls and self.calls[0].ts < now - LOOP_WINDOW:
            self.calls.popleft()
            self._signatures.popleft()

    def snapshot(self, now: float | None = None) -> Snapshot:
        now = time.time() if now is None else now
        self._prune(now)
        rate_tokens = sum(e.tokens for e in self.calls if e.ts >= now - RATE_WINDOW)
        recent_calls = sum(1 for e in self.calls if e.ts >= now - CALLS_WINDOW)
        repeats = Counter(e.prompt_hash for e in self.calls if e.prompt)
        recent = [s for e, s in zip(self.calls, self._signatures) if s and e.ts >= now - SIMILAR_WINDOW]
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
            similar_repeats=biggest_cluster(recent),
        )

    def recent_events(self, n: int = 12) -> list[AgentEvent]:
        return list(self.calls)[-n:]
