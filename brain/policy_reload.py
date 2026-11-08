"""
Policy hot reload (CONTRACTS §11, added 8 Nov).

The brain must be able to pick up a changed `policies.yaml` **while it runs** — an operator
edits a rule, and within a tick the tool gate decides differently. No restart, no dropped
requests.

The rules of the swap:

  - the file's mtime is checked (cheap) — only a *change* triggers a load
  - a **valid** file is swapped in atomically, and a `POLICY_RELOAD` action is recorded
  - an **invalid** file is REJECTED: the last good policy stays in force and a critical
    `policy_invalid` alert carries the errors

"Atomically" means the running policy object is replaced in one step, so a tool call is never
decided by half a policy.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from brain.policy import Policy
from shared.contracts import ActionRow, AlertRow, utc_now_iso

log = logging.getLogger("brain.policy_reload")

# The agent the reload is filed under. A policy is fleet-wide, so it is not any one agent's
# business — but the actions table needs an agent id, and "" is what the table already uses
# for fleet-wide rows.
POLICY_ACTOR = "policy"


@dataclass
class ReloadResult:
    """What happened when the policy file was looked at."""

    changed: bool = False       # the file changed since the last look
    loaded: bool = False        # a new policy is in force
    version: str = ""           # the version of the policy now in force
    errors: list[str] = field(default_factory=list)   # why the new file was rejected
    summary: str = ""           # one line: what changed

    def to_dict(self) -> dict:
        return {"changed": self.changed, "loaded": self.loaded, "version": self.version,
                "errors": list(self.errors), "summary": self.summary}


class PolicyManager:
    """
    Owns the policy that is in force and watches the file for changes.

    The manager is the only thing allowed to swap the policy, so the swap happens in one place.
    """

    def __init__(self, policy: Policy, path: str, store=None, default_budget: float = 0.5):
        self.policy = policy
        self.path = path
        self.store = store
        self.default_budget = default_budget
        self.last_error: str = ""          # the errors of the last rejected file ("" = the policy is good)
        self.last_mtime: float = 0.0
        self.last_checked: float = 0.0
        self.reload_count = 0
        self._mtime = self._read_mtime()

    # ── reading ──
    def _read_mtime(self) -> float:
        """The file's mtime, or 0.0 if it cannot be read."""
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def view(self) -> dict:
        """The policy in force, as the API serves it (CONTRACTS §6, PolicyView)."""
        data = self.policy.to_dict()
        data["last_error"] = self.last_error
        return data

    # ── the watch ──
    def check(self, now: Optional[float] = None, force: bool = False) -> ReloadResult:
        """
        Look at the policy file. If it changed, load it.

        Returns what happened. A rejected file never replaces the policy in force.
        """
        now = time.time() if now is None else now
        mtime = self._read_mtime()
        result = ReloadResult(version=self.policy.version)

        if not force and mtime == self._mtime:
            return result        # nothing changed — the cheap path, and it is the common one

        self._mtime = mtime
        result.changed = True

        try:
            text = Path(self.path).read_text(encoding="utf-8")
        except FileNotFoundError:
            # The file was deleted. The last good policy stays in force — removing the rules
            # would silently open the fleet up, so it takes a human to do that on purpose.
            errors = [f"policy: {self.path} does not exist — the last good policy stays in force"]
            return self._reject(result, errors)
        except OSError as exc:
            return self._reject(result, [f"policy: {self.path} could not be read ({exc})"])

        new_policy, errors = Policy.from_text(text, source=self.path, default_budget=self.default_budget)
        if errors:
            return self._reject(result, errors)

        old = self.policy
        # The swap: one assignment, so no tool call ever sees half a policy.
        self.policy = new_policy
        self.last_error = ""
        self.reload_count += 1
        result.loaded = True
        result.version = new_policy.version
        result.summary = summarize(old, new_policy)
        log.warning("policy reloaded (%s): %s", new_policy.version, result.summary)
        self._record_action(result)
        return result

    def reload_now(self) -> ReloadResult:
        """Re-read the file right now, even if its mtime has not changed."""
        self._mtime = -1.0
        return self.check(force=True)

    # ── what it writes ──
    def _reject(self, result: ReloadResult, errors: list[str]) -> ReloadResult:
        """Keep the last good policy and raise a critical alert."""
        self.last_error = "; ".join(errors)
        result.errors = list(errors)
        result.version = self.policy.version
        result.summary = f"rejected — {self.last_error}"
        log.error("the policy file %s was rejected: %s", self.path, self.last_error)
        self._record_alert(errors)
        return result

    def _record_action(self, result: ReloadResult) -> None:
        if self.store is None:
            return
        try:
            self.store.insert_action(ActionRow("", "POLICY_RELOAD", POLICY_ACTOR,
                                               f"{self.path}: {result.summary}", 0.0, 0))
        except Exception:
            log.exception("could not record the policy reload")

    def _record_alert(self, errors: list[str]) -> None:
        if self.store is None:
            return
        try:
            self.store.insert_alert(AlertRow("", "critical", "policy_invalid",
                                            f"{self.path}: {self.last_error}"))
        except Exception:
            log.exception("could not record the policy_invalid alert")


def summarize(old: Policy, new: Policy) -> str:
    """One line describing what changed between two policies."""
    bits: list[str] = []
    if old.budget_usd != new.budget_usd:
        bits.append(f"budget ${old.budget_usd:.2f} → ${new.budget_usd:.2f}")
    if old.on_trip != new.on_trip:
        bits.append(f"on_trip {old.on_trip} → {new.on_trip}")
    if old.on_hard_limit != new.on_hard_limit:
        bits.append(f"on_hard_limit {old.on_hard_limit} → {new.on_hard_limit}")
    for agent in sorted(set(old.agents) | set(new.agents)):
        before = old.agents.get(agent, {}).get("budget_usd")
        after = new.agents.get(agent, {}).get("budget_usd")
        if before != after:
            bits.append(f"{agent} budget ${float(before or 0):.2f} → ${float(after or 0):.2f}")
    old_rules = {r.match for r in old.tools}
    new_rules = {r.match for r in new.tools}
    if old_rules != new_rules:
        added = sorted(new_rules - old_rules)
        removed = sorted(old_rules - new_rules)
        if added:
            bits.append(f"+{len(added)} rule(s): {', '.join(added[:3])}")
        if removed:
            bits.append(f"-{len(removed)} rule(s): {', '.join(removed[:3])}")
    elif len(old.tools) != len(new.tools):
        bits.append(f"{len(old.tools)} → {len(new.tools)} rules")
    else:
        bits.append("same rules")
    return ", ".join(bits)


__all__ = ["POLICY_ACTOR", "PolicyManager", "ReloadResult", "summarize"]
