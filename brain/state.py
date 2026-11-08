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


# How many prompt scores the cache keeps per agent (A11). The window holds 16, so 64
# entries is four windows' worth — enough that a prompt is still cached after it left
# the window, and small enough that the cache cannot grow without bound.
_INJECTION_CACHE_SIZE = 64


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
        # A11: the two scores that used to be recomputed from scratch on every tick.
        # The loop score is incremental (only the new prompts are clustered), and the
        # injection score is cached by the text — the same prompt scores the same every
        # time, and the window slides by one prompt at a time.
        self.loop_score = loops.IncrementalLoopScore()
        self._injection: dict[str, float] = {}   # prompt → its injection score

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
        # B9: one pass over the chats instead of four.
        #
        # The tick calls this once per agent, so at 1000 agents the walks below were
        # walked 4,000 times a second-and-a-bit. The old code made four passes over
        # the same deque — one for the rate window, one for the tokens, one for the
        # dollars, one for the recent calls — and then two more for the prompts and
        # the repeat counter. Each pass re-read `start_ts` and re-did the float()
        # coercion the span was already coerced for when it was added.
        #
        # The two windows are nested (CALLS_WINDOW is inside RATE_WINDOW), so one
        # walk can serve both: a chat older than the rate window counts for
        # neither, a chat inside the calls window counts for both, and a chat in
        # between counts only for the rate. The numbers are the same numbers; they
        # are just arrived at once.
        rate_cutoff = now - RATE_WINDOW
        calls_cutoff = now - CALLS_WINDOW
        tokens = 0
        usd = 0.0
        recent_calls = 0
        prompts: list[str] = []
        repeats: Counter = Counter()
        for chat in self.chats:
            ts = float(chat["start_ts"])
            if ts >= rate_cutoff:
                tokens += int(chat.get("input_tokens") or 0) + int(chat.get("output_tokens") or 0)
                usd += float(chat.get("cost_usd") or 0)
                if ts >= calls_cutoff:
                    recent_calls += 1
            prompts.append(chat.get("prompt_preview") or "")
            prompt_hash = chat.get("prompt_hash")
            if prompt_hash:
                repeats[prompt_hash] += 1
        tool_names = [t.get("tool_name") or "" for t in self.tools]
        recent = prompts[-12:]
        injection_score, injection_hits = self._injection_scores(recent)
        return Snapshot(
            agent_id=self.agent_id,
            tokens_per_min=int(tokens * 60 / RATE_WINDOW),
            usd_per_min=round(usd * 60 / RATE_WINDOW, 5),
            calls_per_sec=round(recent_calls / CALLS_WINDOW, 2),
            total_tokens=self.total_tokens,
            spend_usd=round(self.spend_usd, 5),
            budget_usd=budget_usd,
            exact_repeats=max(repeats.values(), default=0),
            # A11: incremental — only the prompts that are new are clustered.
            loop_score=self.loop_score.score(prompts),
            tool_cycle=loops.tool_cycle(tool_names),
            injection_hits=injection_hits,
            injection_score=injection_score,
            memory_mb=self.memory_mb,
            memory_pct=self.memory_pct,
            calls_in_window=len(self.chats),
        )

    def _injection_scores(self, prompts: list[str]) -> tuple[float, int]:
        """The worst injection score among the recent prompts, and how many fired.

        A11: the score of a prompt never changes, so it is cached by the text. The
        window slides by one prompt at a time, so without the cache every tick
        re-scored the same 12 prompts — twice, because the count and the maximum
        were computed separately.
        """
        from brain.injection import FINDING_SCORE, score_text

        worst = 0.0
        hits = 0
        for prompt in prompts:
            if not prompt:
                continue
            score = self._injection.get(prompt)
            if score is None:
                score = score_text(prompt).score
                self._injection[prompt] = score
                # The cache must not grow without bound: an agent that talks for hours
                # would otherwise leave a score behind for every prompt it ever sent.
                if len(self._injection) > _INJECTION_CACHE_SIZE:
                    self._injection.clear()
            if score > worst:
                worst = score
            if score >= FINDING_SCORE:
                hits += 1
        return worst, hits

    def recent_prompts(self, n: int = 12) -> list[dict]:
        return [{"t": round(float(c["start_ts"]), 1), "tokens": int(c.get("input_tokens") or 0)
                 + int(c.get("output_tokens") or 0), "prompt": (c.get("prompt_preview") or "")[:200]}
                for c in list(self.chats)[-n:]]

    def recent_tools(self, n: int = 12) -> list[dict]:
        return [{"tool": t.get("tool_name"), "status": t.get("status")} for t in list(self.tools)[-n:]]
