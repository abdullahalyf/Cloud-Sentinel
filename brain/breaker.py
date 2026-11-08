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

from brain.budget import Ladder
from brain.detectors import Finding, Level

CLEAR_AFTER_SECONDS = 30.0   # suspicious → healthy after this long without findings


@dataclass
class Effect:
    action: str        # PAUSE | KILL | RESUME | RESTART | WARN | THROTTLE | DOWNGRADE
    actor: str         # rules | claude | gemini | fallback | human | mcp
    reason: str


class Breaker:
    def __init__(self, agent_id: str, probation_seconds: float = 30.0, kill_confidence: float = 0.6,
                 on_trip: str = "pause", on_hard_limit: str = "kill", state: str = "healthy",
                 ladder: Optional[Ladder] = None):
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
        # B4: the degradation ladder. With it disabled (the default) the breaker does exactly
        # what it always did — pause or kill, straight away. With it enabled the breaker asks
        # the ladder for the next rung instead, so the agent is stepped down gently first.
        self.ladder = ladder if ladder is not None else Ladder(agent_id, enabled=False)

    @property
    def active(self) -> bool:
        """True while the agent is running and must be watched."""
        return self.state in ("healthy", "suspicious", "probation")

    def _trip(self, mode: str, actor: str, reason: str) -> Effect:
        # B4: when the ladder is on, the trip becomes "ask the ladder what to do". The ladder
        # answers with the next rung — THROTTLE first, DOWNGRADE next, PAUSE, then KILL — and
        # the agent stays *active* until the ladder reaches a rung that stops it for good.
        # A ladder that is off (the default) falls through to the old behaviour below.
        if self.ladder.enabled:
            rung = self.ladder.next_step()
            if rung in ("THROTTLE", "DOWNGRADE"):
                # A throttle does not stop the agent, so the breaker stays active and keeps
                # watching it. That is the point: the gentler step is *not* a stopping point.
                return Effect(rung, actor, reason)
            if rung == "PAUSE":
                self.state = "paused"
                return Effect("PAUSE", actor, reason)
            if rung == "KILL":
                self.state = "killed"
                return Effect("KILL", actor, reason)
            # The ladder is exhausted and every rung has been tried: fall through to the old
            # behaviour, which kills. An agent that survived throttle, downgrade and pause is
            # not going to be saved by another warning.
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
            # B4: the agent is healthy again, so the ladder starts from the top.
            # A throttle that is no longer needed must not count as a step that
            # was already taken — the next runaway gets a fresh, gentle walk.
            self.ladder.reset()
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
            # B4: a resumed agent gets a fresh ladder — the old walk was for the
            # incident that is over.
            self.ladder.reset()
            return Effect("RESUME", actor, reason or "resumed on probation")
        if command == "KILL" and self.state != "killed":
            self.state = "killed"
            return Effect("KILL", actor, reason or "emergency kill switch")
        if command == "RESTART" and self.state == "killed":
            self.state, self.probation_until = "probation", now + self.probation_seconds
            self.ladder.reset()
            return Effect("RESTART", actor, reason or "restarted on probation")
        return None

    def on_runtime_status(self, status: str) -> None:
        """Keep the FSM honest if the container changed outside of us (crash, manual docker stop)."""
        if status == "exited" and self.state != "killed":
            self.state = "killed"
        elif status == "paused" and self.active:
            self.state = "paused"
