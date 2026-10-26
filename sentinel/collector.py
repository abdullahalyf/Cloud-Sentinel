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
MEMORY_WINDOW = 5.0     # seconds of memory readings used to measure how fast memory grows
MIN_GROWTH_MB = 20.0    # ...and it must have grown at least this much, so start-up noise is ignored

STOPWORDS = frozenset("""a an and the of to for on in at by with from as is are was be it its this that these those
or if then so up out off over again also please try retry once more still need what where which who how me my
you your i we us our can could would should will just yet back short answer result report tell find info""".split())
NUMBER = re.compile(r"\d{3,}")   # id-like numbers only: 4471, not "top 10"
YEAR = re.compile(r"(?:19|20)\d\d")   # a year like 2026 is shared by many prompts: not an id
WORD = re.compile(r"[a-z][a-z']+")


def signature(prompt: str) -> tuple[frozenset[str], frozenset[str]]:
    """(ids, content words) of a prompt. 'order #4471' and 'Order 4471!' share a signature part;
    words are lowercased, stopwords dropped and a plural 's' removed. Ids = numbers of 3+ digits, years excluded."""
    text = prompt.lower()
    words = {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in WORD.findall(text)} - STOPWORDS
    ids = {n for n in NUMBER.findall(text) if not YEAR.fullmatch(n)}
    return frozenset(ids), frozenset(words)


def similar(a: tuple[frozenset[str], frozenset[str]], b: tuple[frozenset[str], frozenset[str]]) -> bool:
    """Same job, other words? Needs the same ids (order 4471) as the anchor: prompts about different ids
    never match (different work), and prompts without any id are never counted (a template with other
    names is normal work). Then at least a third of the shorter word list must be shared."""
    (ids_a, words_a), (ids_b, words_b) = a, b
    if not ids_a or ids_a != ids_b or not words_a or not words_b:
        return False
    shared = len(words_a & words_b)
    return shared > 0 and shared / min(len(words_a), len(words_b)) >= 0.3


def biggest_cluster(signatures: list[tuple[frozenset[str], frozenset[str]]]) -> int:
    """Size of the biggest group of prompts that are all similar to ONE anchor prompt.
    Comparing to an anchor (not chaining A~B~C...) stops slowly drifting wording from joining up.
    Prompts without an id are never counted (0 when there are none)."""
    return max((sum(similar(anchor, other) for other in signatures) for anchor in signatures
                if anchor[0]), default=0)


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
    memory_mb_per_s: float = 0.0   # how fast memory has been growing (last ~5s)

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
        self._memory: deque[tuple[float, float]] = deque()   # (time, MB) readings of the last few seconds
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

    def set_memory(self, memory_mb: float, memory_pct: float, now: float | None = None) -> None:
        self.memory_mb, self.memory_pct = memory_mb, memory_pct
        if memory_mb > 0:   # 0 = "no reading yet", not a real value
            self._memory.append((time.time() if now is None else now, memory_mb))

    def memory_growth(self, now: float) -> float:
        """MB per second over the last MEMORY_WINDOW seconds (0 unless it grew by MIN_GROWTH_MB or more)."""
        while self._memory and self._memory[0][0] < now - MEMORY_WINDOW:
            self._memory.popleft()
        if len(self._memory) < 2:
            return 0.0
        (t0, mb0), (t1, mb1) = self._memory[0], self._memory[-1]
        grown = mb1 - mb0
        return grown / (t1 - t0) if t1 - t0 >= 1.0 and grown >= MIN_GROWTH_MB else 0.0

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
            memory_mb_per_s=self.memory_growth(now),
        )

    def recent_events(self, n: int = 12) -> list[AgentEvent]:
        return list(self.calls)[-n:]
