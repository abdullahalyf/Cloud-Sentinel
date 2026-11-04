"""
Policy-as-code (CONTRACTS §11): budgets, what a tripped breaker does, and tool-call rules.
Loaded from brain/policies.yaml. A broken file never crashes the brain — defaults are used instead.
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass
class Policy:
    budget_usd: float = 0.5
    on_trip: str = "pause"         # what a confident judge verdict does: pause | kill
    on_hard_limit: str = "kill"
    agents: dict[str, dict] = field(default_factory=dict)
    tools: list[ToolRule] = field(default_factory=list)

    def budget_for(self, agent_id: str) -> float:
        return float(self.agents.get(agent_id, {}).get("budget_usd", self.budget_usd))

    def decide_tool(self, tool_name: str, args: dict) -> tuple[str, str]:
        """First matching rule wins. Returns (allow|deny|approval, reason)."""
        for rule in self.tools:
            if rule.applies(tool_name, args):
                return rule.action, rule.reason or f"policy rule '{rule.match}'"
        return "allow", "no rule matched"

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
        try:
            import yaml

            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            return cls.from_dict(data, default_budget)
        except FileNotFoundError:
            log.warning("No policy file at %s — using defaults", path)
        except Exception as exc:  # broken YAML must never stop the guard
            log.error("Bad policy file %s (%s) — using defaults", path, exc)
        return cls(budget_usd=default_budget)
