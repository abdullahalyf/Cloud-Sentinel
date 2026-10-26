"""
CloudSentinel — THE CONTRACT.

Every team member's code talks to every other member's code ONLY through the
shapes defined in this file. If you need to change something here, open a PR
and tag Alif + Taseen. Do NOT change it silently — it will break other people.

Pure standard library on purpose: this file is copied into the agent Docker
image too, so it must not import anything that isn't built into Python.

Three contracts live here:
  1. LOG PROTOCOL   — what an AI agent prints to stdout (Fojle → Alif)
  2. DATABASE ROWS  — what the sentinel writes / dashboard reads (Alif → Tamjid)
  3. COMMANDS       — what the dashboard asks the sentinel to do (Tamjid → Alif)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

PROTOCOL_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 1. LOG PROTOCOL  (agent container stdout → sentinel)
# ─────────────────────────────────────────────────────────────────────────────
# An agent prints ONE JSON object per line. Lines without "cs": 1 are ignored,
# so agents may print normal logs too.
#
#   {"cs": 1, "type": "llm_call", "agent": "alpha", "ts": 1730000000.12,
#    "tokens_in": 320, "tokens_out": 180, "model": "sim-model", "prompt": "..."}
#
EventType = Literal["llm_call", "heartbeat", "task_done", "error"]


@dataclass
class AgentEvent:
    agent: str
    type: str
    ts: float = field(default_factory=time.time)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    prompt: str = ""
    message: str = ""

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def prompt_hash(self) -> str:
        """Same prompt → same hash. Used for infinite-loop detection."""
        return hashlib.sha1(self.prompt.strip().lower().encode()).hexdigest()[:12]

    def to_line(self) -> str:
        return json.dumps({"cs": PROTOCOL_VERSION, **asdict(self)}, ensure_ascii=False)

    @classmethod
    def parse_line(cls, line: str) -> Optional["AgentEvent"]:
        """Return an AgentEvent, or None if the line isn't a CloudSentinel event."""
        line = line.strip()
        if not line.startswith("{"):
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or data.get("cs") != PROTOCOL_VERSION:
            return None
        try:
            return cls(
                agent=str(data.get("agent", "unknown")),
                type=str(data.get("type", "unknown")),
                ts=float(data.get("ts", time.time())),
                tokens_in=int(data.get("tokens_in", 0)),
                tokens_out=int(data.get("tokens_out", 0)),
                model=str(data.get("model", "")),
                prompt=str(data.get("prompt", ""))[:2000],
                message=str(data.get("message", ""))[:2000],
            )
        except (TypeError, ValueError):
            return None


def emit(agent: str, type: str, **fields: Any) -> None:
    """Helper for agents: print one protocol line and flush immediately."""
    print(AgentEvent(agent=agent, type=type, **fields).to_line(), flush=True)
    sys.stdout.flush()


# ─────────────────────────────────────────────────────────────────────────────
# 2. DATABASE ROWS  (sentinel → database → dashboard)
#    Table definitions: db/schema.sql   — keep both in sync!
# ─────────────────────────────────────────────────────────────────────────────
AgentStatus = Literal["running", "warned", "paused", "killed"]
Severity = Literal["info", "warning", "critical"]
Actor = Literal["rules", "claude", "gemini", "fallback", "human"]


@dataclass
class MetricRow:
    """One snapshot of one agent, written every tick. Table: agent_metrics"""
    agent: str
    container_id: str
    tokens_per_min: int
    calls_per_sec: float
    total_tokens: int
    token_budget: int
    loop_repeats: int          # how many times the most-repeated prompt appeared
    memory_mb: float
    memory_pct: float
    status: str = "running"
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class AlertRow:
    """Something looked wrong. Table: alerts"""
    agent: str
    severity: str
    rule: str                  # e.g. "loop_detected", "token_spike", "claude_verdict"
    message: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class ActionRow:
    """Something was DONE to an agent (kill / warn / pause). Table: actions"""
    agent: str
    action: str                # "KILL" | "WARN" | "PAUSE"
    actor: str                 # who decided: rules | claude | gemini | fallback | human
    reason: str
    tokens_saved_estimate: int = 0
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# 3. COMMANDS  (dashboard → database → sentinel)
#    The dashboard never touches Docker directly. It inserts a command row,
#    the sentinel picks it up on its next tick (~1s) and executes it.
#    Table: commands
# ─────────────────────────────────────────────────────────────────────────────
CommandType = Literal["KILL", "GO_ROGUE", "PAUSE", "RESUME"]
CommandStatus = Literal["pending", "done", "failed"]


@dataclass
class CommandRow:
    agent: str
    command: str               # "KILL" | "GO_ROGUE" | "PAUSE" | "RESUME"
    requested_by: str = "dashboard"
    reason: str = ""
    status: str = "pending"
    result: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        return asdict(self)
