"""
Policy-as-code (CONTRACTS §11): budgets, what a tripped breaker does, and tool-call rules.
Loaded from brain/policies.yaml. A broken file never crashes the brain — defaults are used instead.

Since 8 Nov the policy can also be **hot reloaded**: the brain watches the file's mtime and swaps in
a new policy as soon as it is valid (brain/engine.py). A policy therefore carries a `version`
(sha256 of the file it came from) so the dashboard can tell two policies apart.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("brain.policy")

OPS = {
    "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b, "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
}


@dataclass
class ToolRule:
    match: str
    action: str                    # allow | deny | approval
    reason: str = ""
    when: dict | None = None       # {"arg": "amount", "op": "gt", "value": 5000}

    def applies(self, tool_name: str, args: dict) -> bool:
        if not fnmatch.fnmatch(tool_name, self.match):
            return False
        if not self.when:
            return True
        arg, op, value = self.when.get("arg"), self.when.get("op", "eq"), self.when.get("value")
        if arg not in args or op not in OPS:
            return False
        try:
            return bool(OPS[op](args[arg], value))
        except TypeError:
            return False

    def to_dict(self) -> dict:
        rule = {"match": self.match, "action": self.action, "reason": self.reason}
        if self.when:
            rule["when"] = dict(self.when)
        return rule


@dataclass
class Policy:
    budget_usd: float = 0.5
    on_trip: str = "pause"         # what a confident judge verdict does: pause | kill
    on_hard_limit: str = "kill"
    agents: dict[str, dict] = field(default_factory=dict)
    tools: list[ToolRule] = field(default_factory=list)
    version: str = ""             # sha256 of the file this came from (12 chars); "" = the built-in defaults
    source: str = ""              # where it was loaded from
    loaded_at: str = ""           # when it was loaded (ISO)

    def budget_for(self, agent_id: str) -> float:
        return float(self.agents.get(agent_id, {}).get("budget_usd", self.budget_usd))

    def decide_tool(self, tool_name: str, args: dict) -> tuple[str, str]:
        """First matching rule wins. Returns (allow|deny|approval, reason)."""
        for rule in self.tools:
            if rule.applies(tool_name, args):
                return rule.action, rule.reason or f"policy rule '{rule.match}'"
        return "allow", "no rule matched"

    def to_dict(self) -> dict:
        """The policy as the API serves it (CONTRACTS §6, PolicyView)."""
        return {
            "version": self.version,
            "loaded_at": self.loaded_at,
            "source": self.source,
            "defaults": {"budget_usd": self.budget_usd, "on_trip": self.on_trip,
                         "on_hard_limit": self.on_hard_limit},
            "agents": {k: dict(v) for k, v in self.agents.items()},
            "tools": [t.to_dict() for t in self.tools],
            "last_error": "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_budget: float = 0.5) -> "Policy":
        d = data.get("defaults", {}) or {}
        rules = [ToolRule(r["match"], r.get("action", "allow"), r.get("reason", ""), r.get("when"))
                 for r in (data.get("tools") or []) if isinstance(r, dict) and "match" in r]
        return cls(budget_usd=float(d.get("budget_usd", default_budget)),
                   on_trip=str(d.get("on_trip", "pause")), on_hard_limit=str(d.get("on_hard_limit", "kill")),
                   agents=data.get("agents") or {}, tools=rules)

    @classmethod
    def load(cls, path: str, default_budget: float = 0.5) -> "Policy":
        """Load a policy file. A missing or broken file never crashes the brain — defaults are used."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            log.warning("No policy file at %s — using defaults", path)
            return cls(budget_usd=default_budget, source=path)
        except OSError as exc:
            log.error("Could not read the policy file %s (%s) — using defaults", path, exc)
            return cls(budget_usd=default_budget, source=path)

        errors = validate_yaml(text)
        if errors:
            log.error("Bad policy file %s (%s) — using defaults", path, "; ".join(errors[:3]))
            return cls(budget_usd=default_budget, source=path)

        import yaml

        try:
            data = yaml.safe_load(text) or {}
        except Exception as exc:  # unreachable: validate_yaml already parsed it
            log.error("Bad policy file %s (%s) — using defaults", path, exc)
            return cls(budget_usd=default_budget, source=path)
        policy = cls.from_dict(data, default_budget)
        policy.version = version_of(text)
        policy.source = path
        policy.loaded_at = utc_now_iso()
        return policy

    @classmethod
    def from_text(cls, text: str, source: str = "<text>", default_budget: float = 0.5) -> tuple["Policy", list[str]]:
        """
        Parse and validate a policy from text. Returns (policy, errors).

        The policy is only meaningful when the error list is empty — a broken policy must never
        replace the one in force.
        """
        errors = validate_yaml(text)
        if errors:
            return cls(budget_usd=default_budget, source=source), errors
        import yaml

        data = yaml.safe_load(text) or {}
        policy = cls.from_dict(data, default_budget)
        policy.version = version_of(text)
        policy.source = source
        policy.loaded_at = utc_now_iso()
        return policy, []


def version_of(text: str) -> str:
    """The version of a policy: the first 12 chars of the sha256 of the file it came from."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def utc_now_iso() -> str:
    from shared.contracts import utc_now_iso as _now

    return _now()


def validate_yaml(text: str) -> list[str]:
    """The validation errors of a policy file's text (empty = good). See brain/policy_schema.py."""
    from brain.policy_schema import validate_yaml as _validate

    return _validate(text)


__all__ = ["OPS", "Policy", "ToolRule", "validate_yaml", "version_of"]
