"""
Hardening for the CloudSentinel MCP server (A7).

Three things live here, and none of them need the MCP SDK:

  * input validation — every tool argument is checked before it reaches the API, so a
    caller gets a clear message instead of a stack trace or a 400 from the other side
  * a rate limit — destructive calls are capped per session, so a runaway loop of tool
    calls cannot turn into a flood of commands against the fleet
  * the read-only gate — with CS_MCP_READONLY=true the server exposes only the tools that
    change nothing

The rate limiter is a plain sliding window over a deque of timestamps. It is per *process*,
which is per MCP session: a stdio server is one session, and an HTTP server is one session
per server process. That is the right granularity for "a session" — the limit protects the
fleet from one chat client, not from a fleet of clients.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Iterable, Optional

from mcp.server.mcpserver.exceptions import ToolError as _SdkToolError

# ── validation ───────────────────────────────────────────────────────────────
MAX_AGENT_ID = 64
MAX_REASON = 500
MAX_YAML = 200_000
MAX_CONTENT_BYTES = 64_000        # the same limit the API enforces on a memory write
MAX_MEMORY_KEYS = 100
MAX_CALL_ID = 2 ** 31
MAX_PROPOSAL_ID = 2 ** 31

AGENT_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")

DECISIONS = ("allow", "deny", "rewrite")
HEAL_DECISIONS = ("apply", "reject")
POLICY_STATUSES = ("pending", "applied", "rejected", "expired")


class ToolError(_SdkToolError):
    """
    A bad argument. The MCP layer turns this into a readable message, never a stack trace.

    It subclasses the SDK's ToolError on purpose: the SDK only passes the *message* of an
    anticipated ToolError to the model. A plain Exception would be treated as a crash, and
    the model would see nothing but "Error executing tool pause_agent" — which is exactly
    the stack-trace-free behaviour we want, except it also hides the reason.
    """

    def __init__(self, message: str, field: str = ""):
        super().__init__(message)
        self.message = message
        self.field = field

    def __str__(self) -> str:  # the message is what the model sees
        return self.message


def check_agent_id(agent_id: Any) -> str:
    """The agent id must be a short, safe identifier — it goes into a URL."""
    if not isinstance(agent_id, str):
        raise ToolError("agent_id must be a string", "agent_id")
    value = agent_id.strip()
    if not value:
        raise ToolError("agent_id must not be empty", "agent_id")
    if len(value) > MAX_AGENT_ID:
        raise ToolError(f"agent_id must be at most {MAX_AGENT_ID} characters", "agent_id")
    bad = [c for c in value if c not in AGENT_ID_CHARS]
    if bad:
        raise ToolError(f"agent_id may only contain letters, digits, '.', '_' and '-' "
                        f"(found {''.join(sorted(set(bad)))!r})", "agent_id")
    return value


def check_reason(reason: Any, required: bool = True) -> str:
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise ToolError("reason must be a string", "reason")
    value = reason.strip()
    if required and not value:
        raise ToolError("reason is required — it is written to the audit log", "reason")
    if len(value) > MAX_REASON:
        raise ToolError(f"reason must be at most {MAX_REASON} characters", "reason")
    return value


def check_choice(value: Any, allowed: Iterable[str], field: str) -> str:
    allowed = tuple(allowed)
    if not isinstance(value, str):
        raise ToolError(f"{field} must be a string", field)
    text = value.strip().lower()
    if text not in allowed:
        raise ToolError(f"{field} must be one of {', '.join(allowed)}", field)
    return text


def check_positive_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"{field} must be a number", field)
    number = int(value)
    if number <= 0 or number > MAX_CALL_ID:
        raise ToolError(f"{field} must be a positive integer", field)
    return number


def check_number(value: Any, field: str, minimum: float = 0.0, maximum: float = 1000.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"{field} must be a number", field)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ToolError(f"{field} must be a finite number", field)
    if number < minimum or number > maximum:
        raise ToolError(f"{field} must be between {minimum} and {maximum}", field)
    return number


def check_content(content: Any) -> dict:
    """A memory write: a small JSON object, like the API requires."""
    if not isinstance(content, dict):
        raise ToolError("content must be a JSON object (key → value)", "content")
    if len(content) > MAX_MEMORY_KEYS:
        raise ToolError(f"content may have at most {MAX_MEMORY_KEYS} keys", "content")
    import json

    try:
        size = len(json.dumps(content, default=str))
    except (TypeError, ValueError):
        raise ToolError("content must be JSON-serialisable", "content")
    if size > MAX_CONTENT_BYTES:
        raise ToolError(f"content must be at most {MAX_CONTENT_BYTES} bytes", "content")
    return content


def check_yaml(yaml: Any) -> str:
    if not isinstance(yaml, str):
        raise ToolError("yaml must be a string", "yaml")
    if not yaml.strip():
        raise ToolError("yaml must not be empty", "yaml")
    if len(yaml) > MAX_YAML:
        raise ToolError(f"yaml must be at most {MAX_YAML} characters", "yaml")
    return yaml


# ── rate limit ───────────────────────────────────────────────────────────────
class RateLimiter:
    """
    A sliding window over the last `limit` calls, per session.

    `allow()` returns (True, "") or (False, "why not"). The window is a deque of
    timestamps, so the oldest entry falls out exactly when it ages past the window —
    no fixed buckets, no drift at the boundary.
    """

    def __init__(self, limit: int = 30, window_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self.limit = max(0, int(limit))
        self.window_seconds = float(window_seconds)
        self.clock = clock
        self.calls: deque[float] = deque()
        self.denied = 0

    def _prune(self, now: float) -> None:
        while self.calls and now - self.calls[0] >= self.window_seconds:
            self.calls.popleft()

    def allow(self) -> tuple[bool, str]:
        if self.limit <= 0:
            return True, ""
        now = self.clock()
        self._prune(now)
        if len(self.calls) >= self.limit:
            self.denied += 1
            wait = self.window_seconds - (now - self.calls[0])
            return False, (f"rate limit reached: at most {self.limit} destructive calls per "
                           f"{int(self.window_seconds)}s. Retry in {max(1, int(wait) + 1)}s.")
        self.calls.append(now)
        return True, ""

    def remaining(self) -> int:
        if self.limit <= 0:
            return self.limit
        self._prune(self.clock())
        return max(0, self.limit - len(self.calls))

    def reset(self) -> None:
        self.calls.clear()


# ── read-only gate ───────────────────────────────────────────────────────────
def tool_is_allowed(tool_name: str, readonly: bool, destructive_tools: Iterable[str]) -> bool:
    """With read-only mode on, only the tools that change nothing are exposed."""
    if not readonly:
        return True
    return tool_name not in set(destructive_tools)


def read_only_tools(all_tools: Iterable[str], destructive_tools: Iterable[str]) -> list[str]:
    destructive = set(destructive_tools)
    return sorted(name for name in all_tools if name not in destructive)


__all__ = ["ToolError", "RateLimiter", "check_agent_id", "check_reason", "check_choice",
           "check_positive_id", "check_number", "check_content", "check_yaml",
           "tool_is_allowed", "read_only_tools"]
