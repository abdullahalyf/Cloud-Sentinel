"""
Circuit-breaker state machine, one per agent (ARCHITECTURE §4). Pure logic: it never calls Docker.
It returns an Effect; the engine executes it (executor + database).

  healthy ──soft──▶ suspicious ──judge PAUSE/KILL──▶ paused ──RESUME──▶ probation ──clean──▶ healthy
     │                  │                              killed ◀──any finding on probation──┘
     └──────HARD────────┴──────────────────────────▶ killed ──RESTART──▶ probation
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from brain.detectors import Finding, Level

CLEAR_AFTER_SECONDS = 30.0   # suspicious → healthy after this long without findings


@dataclass
class Effect:
    action: str        # PAUSE | KILL | RESUME | RESTART | WARN
    actor: str         # rules | claude | gemini | fallback | human | mcp
    reason: str


class Breaker:
    def __init__(self, agent_id: str, probation_seconds: float = 30.0, kill_confidence: float = 0.6,
                 on_trip: str = "pause", on_hard_limit: str = "kill", state: str = "healthy"):
        self.agent_id = agent_id
        self.state = state
        self.probation_seconds = probation_seconds
        self.kill_confidence = kill_confidence
        self.on_trip, self.on_hard_limit = on_trip, on_hard_limit
        self.last_finding_at = 0.0
        self.probation_until = 0.0
        self.warned = False
        # Set after an auto-heal (A3). A second trip then PAUSES instead of KILLING: the patch did
        # not work, so a human has to look — and a pause keeps the state that a kill would destroy.
        self.pause_on_trip = False

    @property
    def active(self) -> bool:
        """True while the agent is running and must be watched."""
        return self.state in ("healthy", "suspicious", "probation")

    def _trip(self, mode: str, actor: str, reason: str) -> Effect:
        if mode == "kill" and self.pause_on_trip:
            # the auto-heal did not work — pause and let a human look, do not destroy the state
            mode = "pause"
        self.state = "killed" if mode == "kill" else "paused"
        return Effect("KILL" if mode == "kill" else "PAUSE", actor, reason)

    # ── detector findings, every tick ──
    def on_finding(self, f: Finding, now: float) -> tuple[Optional[Effect], bool]:
        """Returns (effect, ask_judge)."""
        if not self.active:
            return None, False
        if f.level == Level.CRITICAL:
            mode = "kill" if self.state == "probation" else self.on_hard_limit
            return self._trip(mode, "rules", "Hard limit: " + f.text), False
        if self.state == "probation":
            if f.level == Level.SUSPICIOUS:
                return self._trip("kill", "rules", "Misbehaved again while on probation: " + f.text), False
            if now >= self.probation_until:
                self.state = "healthy"
            return None, False
        if f.level == Level.SUSPICIOUS:
            self.last_finding_at = now
            self.state = "suspicious"
            return None, True
        if self.state == "suspicious" and now - self.last_finding_at >= CLEAR_AFTER_SECONDS:
            self.state, self.warned = "healthy", False
        return None, False

    # ── judge verdicts ──
    def on_verdict(self, action: str, confidence: float, source: str, reason: str) -> Optional[Effect]:
        if self.state != "suspicious":
            return None  # e.g. already killed by a hard limit while the judge was thinking
        if action in ("PAUSE", "KILL") and confidence >= self.kill_confidence:
            mode = "kill" if (action == "KILL" and self.on_trip == "kill") else "pause"
            return self._trip(mode, source, reason)
        if action == "IGNORE":
            self.state = "healthy"
            return None
        if not self.warned:  # WARN, or a not-confident-enough PAUSE/KILL
            self.warned = True
            return Effect("WARN", source, reason)
        return None

    # ── human / MCP commands ──
    def on_command(self, command: str, actor: str, reason: str, now: float) -> Optional[Effect]:
        if command == "PAUSE" and self.active:
            self.state = "paused"
            return Effect("PAUSE", actor, reason or "paused by operator")
        if command == "RESUME" and self.state == "paused":
            self.state, self.probation_until = "probation", now + self.probation_seconds
            return Effect("RESUME", actor, reason or "resumed on probation")
        if command == "KILL" and self.state != "killed":
            self.state = "killed"
            return Effect("KILL", actor, reason or "emergency kill switch")
        if command == "RESTART" and self.state == "killed":
            self.state, self.probation_until = "probation", now + self.probation_seconds
            return Effect("RESTART", actor, reason or "restarted on probation")
        return None

    def on_runtime_status(self, status: str) -> None:
        """Keep the FSM honest if the container changed outside of us (crash, manual docker stop)."""
        if status == "exited" and self.state != "killed":
            self.state = "killed"
        elif status == "paused" and self.active:
            self.state = "paused"
