"""
The judge's hourly spend cap (A12).

The judge is the one part of the brain that costs money on every call. A fleet that
trips forty agents an hour, each asking the judge about itself, is a bill that grows
without a ceiling. `CS_JUDGE_MAX_USD_PER_HOUR` (contract, §3) is that ceiling.

Above the cap the brain stops paying: it uses the deterministic fallback judge and
writes a `judge_cost_capped` alert, so the operator sees both that the agents are
still being judged *and* that the LLM judge is off.

**The window is a rolling hour, not a clock hour.** "An hour" that starts at the top
of the wall-clock hour would let a fleet spend the whole cap in the first minute and
then judge nothing for 59 minutes — the exact opposite of what an operator expects
from a rate limit. The rolling window measures what the last 60 minutes cost.

The clock is injected so the tests can move it. `time.time()` inside the brain is
the wrong clock for this: the engine already runs on a virtual clock in the tests, and
a cap measured against a different clock than the one that produced the events is a
cap nobody can trust.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable, Deque, Optional

log = logging.getLogger("brain.judge_spend")

# The alert rule name. The engine writes one of these when the cap bites.
CAPPED_ALERT_RULE = "judge_cost_capped"


class JudgeSpend:
    """
    What the LLM judge has cost in the last hour.

    `record(cost, now)` adds what one call cost. `capped(now)` says whether the next
    call may be paid for. A cap of 0 means "no cap" — the setting is off by default,
    because a product that stops judging because of a rounding error is worse than
    one that is slightly too expensive.
    """

    def __init__(self, cap_usd_per_hour: float = 0.0,
                 clock: Optional[Callable[[], float]] = None,
                 window_seconds: float = 3600.0):
        self.cap_usd_per_hour = max(0.0, float(cap_usd_per_hour))
        self.window_seconds = float(window_seconds)
        self._clock = clock or time.time
        # (timestamp, cost) of every paid call inside the window
        self._calls: Deque[tuple[float, float]] = deque()

    # ── reading ──────────────────────────────────────────────────────────────
    def spend(self, now: Optional[float] = None) -> float:
        """What the last hour cost, in dollars."""
        t = self._clock() if now is None else now
        self._expire(t)
        return round(sum(c for _, c in self._calls), 8)

    def capped(self, now: Optional[float] = None) -> bool:
        """True when the next LLM call must not be paid for."""
        if not self.cap_usd_per_hour:
            return False
        return self.spend(now) >= self.cap_usd_per_hour

    def remaining(self, now: Optional[float] = None) -> float:
        """How much of the cap is left. 0.0 when there is no cap."""
        if not self.cap_usd_per_hour:
            return 0.0
        return round(max(0.0, self.cap_usd_per_hour - self.spend(now)), 8)

    # ── writing ──────────────────────────────────────────────────────────────
    def record(self, cost_usd: float, now: Optional[float] = None) -> None:
        """Add what one LLM call cost. Zero-cost calls are not recorded."""
        try:
            cost = float(cost_usd)
        except (TypeError, ValueError):
            return
        if cost <= 0:
            return
        t = self._clock() if now is None else now
        self._expire(t)
        self._calls.append((t, cost))

    def reset(self) -> None:
        """Forget everything. Used by the tests and after a cap is raised."""
        self._calls.clear()

    # ── internals ────────────────────────────────────────────────────────────
    def _expire(self, now: float) -> None:
        """Drop the calls that have fallen out of the window."""
        cutoff = now - self.window_seconds
        while self._calls and self._calls[0][0] <= cutoff:
            self._calls.popleft()
