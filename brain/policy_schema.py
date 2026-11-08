"""
Policy file validation (CONTRACTS §11, added 8 Nov). Pure Python, no new dependencies.

A policy file is only allowed to replace the running policy after it passes these checks.
Every error names the exact path of the thing that is wrong, so whoever edited the file
knows what to fix:

    tools[2].when.op: must be one of gt, gte, lt, lte, eq, ne, contains
    defaults.budget_usd: must be a number > 0
    agents.delta.budget_usd: must be a number > 0

The checks are deliberately explicit rather than clever: a policy file is read by people,
not by machines, and "you wrote a typo here" is more useful than a stack trace.
"""
from __future__ import annotations

from typing import Any

# The comparison operators a `when` block may use (CONTRACTS §11). No eval() — ever.
OPS = ("gt", "gte", "lt", "lte", "eq", "ne", "contains")

# What a rule may do to a tool call.
ACTIONS = ("allow", "deny", "approval")

# What a breaker may do when it trips or when a hard limit is broken.
TRIP_ACTIONS = ("pause", "kill")

# The keys `defaults` may hold. Anything else is a typo and is reported.
DEFAULT_KEYS = ("budget_usd", "on_trip", "on_hard_limit")

# The keys an agent block may hold.
AGENT_KEYS = ("budget_usd",)

MAX_ERRORS = 50


class PolicyError:
    """One problem with a policy file, with the path of the offending value."""

    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str):
        self.path, self.message = path, message

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"

    def to_dict(self) -> dict:
        return {"path": self.path, "message": self.message}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PolicyError({self.path!r}, {self.message!r})"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_number(errors: list[PolicyError], path: str, value: Any) -> None:
    if not _is_number(value):
        errors.append(PolicyError(path, "must be a number"))
    elif value <= 0:
        errors.append(PolicyError(path, "must be a number > 0"))


def _one_of(errors: list[PolicyError], path: str, value: Any, allowed: tuple[str, ...]) -> None:
    if not isinstance(value, str):
        errors.append(PolicyError(path, f"must be one of {', '.join(allowed)}"))
    elif value not in allowed:
        errors.append(PolicyError(path, f"must be one of {', '.join(allowed)}"))


def _validate_defaults(errors: list[PolicyError], defaults: Any) -> None:
    if defaults is None:
        return
    if not isinstance(defaults, dict):
        errors.append(PolicyError("defaults", "must be a mapping"))
        return
    for key in sorted(set(defaults) - set(DEFAULT_KEYS)):
        errors.append(PolicyError(f"defaults.{key}", "is not a known setting"))
    if "budget_usd" in defaults:
        _positive_number(errors, "defaults.budget_usd", defaults["budget_usd"])
    for key in ("on_trip", "on_hard_limit"):
        if key in defaults:
            _one_of(errors, f"defaults.{key}", defaults[key], TRIP_ACTIONS)


def _validate_agents(errors: list[PolicyError], agents: Any) -> None:
    if agents is None:
        return
    if not isinstance(agents, dict):
        errors.append(PolicyError("agents", "must be a mapping of agent id → settings"))
        return
    for agent_id in sorted(agents):
        path = f"agents.{agent_id}"
        block = agents[agent_id]
        if not isinstance(block, dict):
            errors.append(PolicyError(path, "must be a mapping"))
            continue
        for key in sorted(set(block) - set(AGENT_KEYS)):
            errors.append(PolicyError(f"{path}.{key}", "is not a known setting"))
        if "budget_usd" in block:
            _positive_number(errors, f"{path}.budget_usd", block["budget_usd"])


def _validate_when(errors: list[PolicyError], path: str, when: Any) -> None:
    if when is None:
        return
    if not isinstance(when, dict):
        errors.append(PolicyError(path, "must be a mapping"))
        return
    if "arg" not in when:
        errors.append(PolicyError(f"{path}.arg", "is required"))
    elif not isinstance(when["arg"], str) or not when["arg"].strip():
        errors.append(PolicyError(f"{path}.arg", "must be a non-empty string"))
    if "op" not in when:
        errors.append(PolicyError(f"{path}.op", "is required"))
    else:
        _one_of(errors, f"{path}.op", when["op"], OPS)
    if "value" not in when:
        errors.append(PolicyError(f"{path}.value", "is required"))
    elif not isinstance(when["value"], (str, int, float, bool)):
        errors.append(PolicyError(f"{path}.value", "must be a string, number or boolean"))


def _validate_tools(errors: list[PolicyError], tools: Any) -> None:
    if tools is None:
        return
    if not isinstance(tools, list):
        errors.append(PolicyError("tools", "must be a list of rules"))
        return
    for i, rule in enumerate(tools):
        path = f"tools[{i}]"
        if not isinstance(rule, dict):
            errors.append(PolicyError(path, "must be a mapping"))
            continue
        if "match" not in rule:
            errors.append(PolicyError(f"{path}.match", "is required"))
        elif not isinstance(rule["match"], str) or not rule["match"].strip():
            errors.append(PolicyError(f"{path}.match", "must be a non-empty glob"))
        if "action" not in rule:
            errors.append(PolicyError(f"{path}.action", "is required"))
        else:
            _one_of(errors, f"{path}.action", rule["action"], ACTIONS)
        if "reason" in rule and not isinstance(rule["reason"], str):
            errors.append(PolicyError(f"{path}.reason", "must be a string"))
        if "when" in rule:
            _validate_when(errors, f"{path}.when", rule["when"])


def validate(data: Any) -> list[PolicyError]:
    """
    Check a parsed policy document. Returns the problems — an empty list means the policy is good.
    """
    errors: list[PolicyError] = []
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return [PolicyError("", "the policy must be a mapping")]
    for key in sorted(set(data) - {"defaults", "agents", "tools"}):
        errors.append(PolicyError(key, "is not a known section"))
    _validate_defaults(errors, data.get("defaults"))
    _validate_agents(errors, data.get("agents"))
    _validate_tools(errors, data.get("tools"))
    return errors


def validate_yaml(text: str) -> list[str]:
    """
    Check a policy file's text. Returns the errors as readable strings ("path: message").

    A file that is not even YAML comes back as one error, not as a traceback.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a hard dependency of the project
        return ["policy: PyYAML is not installed, so the policy cannot be checked"]
    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:
        return [f"policy: not valid YAML ({_one_line(exc)})"]
    return [str(e) for e in validate(data)]


def _one_line(exc: Exception) -> str:
    """YAML errors are multi-line; one line is enough for an alert."""
    return " ".join(str(exc).split())


def error_dicts(errors: list[PolicyError]) -> list[dict]:
    """The errors as plain dicts (the shape the API returns)."""
    return [e.to_dict() for e in errors]


__all__ = ["ACTIONS", "OPS", "TRIP_ACTIONS", "PolicyError", "error_dicts", "validate", "validate_yaml"]
