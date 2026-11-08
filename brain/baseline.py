"""
Adaptive per-agent baselines (A4). Pure Python, no I/O.

A fixed soft limit is right for no agent in particular: a busy analyst is normal at
40k tokens/min, and a chatty support agent is not. So each agent learns what
"normal" means for *it* — a rolling median and MAD (median absolute deviation) over
its own healthy behaviour — and the soft limits move with that.

  median      the middle of the agent's own healthy samples
  MAD         median(|x − median|) — a spread that a single spike cannot inflate
  limit       median + K × 1.4826 × MAD     (1.4826 makes MAD a normal σ)

The limit is clamped so a baseline can never be more permissive than the fixed hard
limit, nor less than a quarter of the fixed soft limit (a very quiet agent would
otherwise trip on its own first real task).

Only HEALTHY windows feed the baseline. A suspicious, paused, probation or killed
agent is not "normal" — learning from it would teach the brain that a runaway is
the new normal.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# 1.4826 ≈ Φ⁻¹(0.75): the constant that turns a MAD into a standard deviation.
MAD_TO_SIGMA = 1.4826

# The metrics we learn a baseline for. Each maps to a fixed soft limit in Settings.
METRICS = ("tokens_per_min", "usd_per_min", "calls_per_sec")

# The soft limit never drops below this fraction of the fixed one (a very quiet
# agent would otherwise trip on its own first real task).
FLOOR_FACTOR = 0.25

# A MAD of zero means every sample was identical, so the limit would be exactly the
# median — and then any normal jitter trips the agent. The spread is therefore never
# allowed to fall below this fraction of the median. A rate metric (calls/s) arrives
# in bursts, so it gets a wider floor than a volume metric (tokens/min).
MIN_SPREAD_RATIO = 0.25
MIN_SPREAD_RATIO_RATE = 1.0

# The ceiling for that floor is the hard limit: a stable agent still gets a limit
# below the hard one, but never a nonsensical one above it.


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _mad(values: list[float], med: float) -> float:
    return _median([abs(v - med) for v in values])


@dataclass
class Baseline:
    """One metric's learned normal: the median, the spread and the limit they imply."""

    median: float = 0.0
    mad: float = 0.0
    limit: float = 0.0
    samples: int = 0

    def to_dict(self) -> dict:
        return {"median": round(self.median, 4), "limit": round(self.limit, 4), "samples": self.samples}

    @classmethod
    def from_dict(cls, data: dict) -> "Baseline":
        return cls(median=float(data.get("median") or 0), mad=float(data.get("mad") or 0),
                   limit=float(data.get("limit") or 0), samples=int(data.get("samples") or 0))


@dataclass
class AgentBaseline:
    """
    What one agent normally does. Holds the raw healthy samples (a rolling window)
    and the limit each metric works out to.
    """

    agent_id: str
    window_seconds: float = 600.0        # the last 10 minutes of healthy windows
    samples: dict = field(default_factory=dict)     # metric → deque[(ts, value)]
    metrics: dict = field(default_factory=dict)     # metric → Baseline

    def __post_init__(self) -> None:
        self.samples = {m: deque() for m in METRICS}
        self.metrics = {m: Baseline() for m in METRICS}

    # ── learning ──
    def observe(self, now: float, values: dict) -> None:
        """Record one healthy window. Only called for a healthy agent."""
        for metric in METRICS:
            value = values.get(metric)
            if value is None:
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(v) or v < 0:
                continue
            self.samples[metric].append((now, v))
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for metric in METRICS:
            dq = self.samples[metric]
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    def recompute(self, cfg) -> None:
        """Recalculate the median, the MAD and the limit of every metric."""
        for metric in METRICS:
            values = [v for _, v in self.samples[metric]]
            if not values:
                continue
            med = _median(values)
            mad = _mad(values, med)
            fixed_soft, fixed_hard = _fixed_limits(cfg, metric)
            # A perfectly stable agent has a MAD of zero, which would make the limit
            # exactly the median — and then its own normal jitter trips it. The spread
            # is floored at a fraction of the median: a wide one for a rate metric,
            # which arrives in bursts, and a narrower one for a volume metric.
            ratio = MIN_SPREAD_RATIO_RATE if metric == "calls_per_sec" else MIN_SPREAD_RATIO
            spread = max(mad, med * ratio)
            self.metrics[metric] = Baseline(median=med, mad=mad,
                                            limit=_clamp(med + cfg.baseline_k * MAD_TO_SIGMA * spread,
                                                         fixed_soft, fixed_hard),
                                            samples=len(values))

    # ── reading ──
    def limit(self, metric: str) -> Optional[float]:
        """The learned limit, or None while the agent has no baseline yet."""
        b = self.metrics.get(metric)
        if b is None or b.samples <= 0:
            return None
        return b.limit

    def ready(self) -> bool:
        """True once every metric has enough samples to be worth trusting."""
        return all(self.metrics[m].samples > 0 for m in METRICS)

    def to_dict(self) -> dict:
        """The JSON stored in agents.baseline: {metric: {median, limit, samples}}."""
        return {m: self.metrics[m].to_dict() for m in METRICS if self.metrics[m].samples > 0}

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, agent_id: str, raw: str | dict | None) -> "AgentBaseline":
        """Rebuild a baseline from what the store kept — this is how a restart keeps it."""
        bl = cls(agent_id=agent_id)
        data = raw
        if isinstance(raw, str):
            try:
                import json

                data = json.loads(raw or "{}")
            except (ValueError, TypeError):
                data = {}
        if not isinstance(data, dict):
            return bl
        for metric, entry in data.items():
            if metric in METRICS and isinstance(entry, dict):
                bl.metrics[metric] = Baseline.from_dict(entry)
        return bl


def _fixed_limits(cfg, metric: str) -> tuple[float, float]:
    """The fixed (soft, hard) limit of a metric."""
    if metric == "tokens_per_min":
        return float(cfg.soft_tokens_per_min), float(cfg.hard_tokens_per_min)
    if metric == "usd_per_min":
        # usd/min has no fixed limit of its own: it is the token limit priced at the
        # simulated model's rate, so the two limits stay consistent with each other.
        per_token = _usd_per_token()
        soft = float(cfg.soft_tokens_per_min) * per_token
        hard = float(cfg.hard_tokens_per_min) * per_token
        return soft, hard
    if metric == "calls_per_sec":
        return float(cfg.soft_calls_per_sec), float(cfg.hard_calls_per_sec)
    return 0.0, 0.0


def _usd_per_token() -> float:
    """The average $/token of the simulated model — used to price the token limits."""
    from shared.pricing import DEFAULT_PRICE

    p_in, p_out = DEFAULT_PRICE
    return (p_in + p_out) / 2 / 1_000_000


def _clamp(limit: float, fixed_soft: float, fixed_hard: float) -> float:
    """
    Keep the learned limit inside sane bounds.

    The hard limit is the ceiling: a baseline may raise the soft limit for a genuinely
    busy agent (a 40k-tokens/min analyst is normal for *it*), but never past the point
    where the hard limit takes over. The floor is a quarter of the fixed soft limit, so
    a very quiet agent is never stopped for doing its (normal) first real task.
    """
    ceiling = fixed_hard if fixed_hard > 0 else fixed_soft
    floor = fixed_soft * FLOOR_FACTOR
    if ceiling <= 0:
        return limit
    if floor > ceiling:
        floor = ceiling
    return max(floor, min(limit, ceiling))


def above_baseline(value: float, baseline: Optional[Baseline]) -> Optional[float]:
    """How many times above its own normal the value is (None without a baseline)."""
    if baseline is None or baseline.samples <= 0 or baseline.median <= 0:
        return None
    return value / baseline.median


def describe(value: float, baseline: Optional[Baseline], metric: str) -> str:
    """The human-readable part of a finding: "3.4× above this agent's normal"."""
    ratio = above_baseline(value, baseline)
    if ratio is None:
        return ""
    return f"{ratio:.1f}× above this agent's normal ({metric})"


__all__ = ["AgentBaseline", "Baseline", "MAD_TO_SIGMA", "METRICS", "above_baseline", "describe"]
