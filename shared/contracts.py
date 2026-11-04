"""
CloudSentinel — THE CONTRACT (v2). Human-readable version: docs/CONTRACTS.md.

Every layer talks to every other layer ONLY through the shapes in this file.
Owners: Alif + Taseen. Do NOT change silently — open a `contract/...` PR (see docs/BRANCHING.md).

Pure standard library on purpose: this file is copied into agent images and used by mocks.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

CONTRACT_VERSION = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_hash(text: str) -> str:
    """Same prompt (ignoring case, spaces and numbers-in-ids) → same hash. Used for exact-loop detection."""
    norm = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


def _dump(value: Any) -> str:
    """JSON-encode dict/list columns (stored as TEXT)."""
    return value if isinstance(value, str) else json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def load_json(value: Any, default: Any = None) -> Any:
    """Decode a JSON TEXT column safely (rows from the DB / API)."""
    if value is None or value == "":
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if default is None else default


# ─────────────────────────────────────────────────────────────────────────────
# Enums (as Literal + tuples so they work without importing Enum everywhere)
# ─────────────────────────────────────────────────────────────────────────────
AgentState = Literal["healthy", "suspicious", "paused", "probation", "killed"]
AGENT_STATES = ("healthy", "suspicious", "paused", "probation", "killed")

JudgeAction = Literal["KILL", "PAUSE", "WARN", "IGNORE"]
JUDGE_ACTIONS = ("KILL", "PAUSE", "WARN", "IGNORE")

ActionType = Literal["KILL", "PAUSE", "RESUME", "RESTART", "WARN", "SET_BUDGET",
                     "MEMORY_EDIT", "TOOL_ALLOW", "TOOL_DENY", "TOOL_REWRITE"]
ACTION_TYPES = ("KILL", "PAUSE", "RESUME", "RESTART", "WARN", "SET_BUDGET",
                "MEMORY_EDIT", "TOOL_ALLOW", "TOOL_DENY", "TOOL_REWRITE")

Actor = Literal["rules", "claude", "gemini", "fallback", "human", "policy", "mcp"]

CommandType = Literal["KILL", "PAUSE", "RESUME", "RESTART", "GO_ROGUE", "SET_BUDGET"]
COMMAND_TYPES = ("KILL", "PAUSE", "RESUME", "RESTART", "GO_ROGUE", "SET_BUDGET")

Pattern = Literal["infinite_loop", "semantic_loop", "token_spike", "memory_leak", "bad_tool_call",
                  "prompt_injection", "legitimate_burst", "other"]
PATTERNS = ("infinite_loop", "semantic_loop", "token_spike", "memory_leak", "bad_tool_call",
            "prompt_injection", "legitimate_burst", "other")

ToolDecision = Literal["pending", "allow", "deny", "rewrite", "timeout"]
TOOL_DECISIONS = ("pending", "allow", "deny", "rewrite", "timeout")

ROGUE_KINDS = ("loop", "paraphrase_loop", "token_bomb", "memory_leak", "bad_tool_call",
               # added 5 Nov (Fojle F6): the simulator implements these; FakeFleet treats them as healthy
               "prompt_injection", "tool_storm", "memory_poisoning", "slow_budget_leak")


# ─────────────────────────────────────────────────────────────────────────────
# 1. OpenTelemetry attribute names (CONTRACTS §4)
# ─────────────────────────────────────────────────────────────────────────────
class Attr:
    OPERATION = "gen_ai.operation.name"
    PROVIDER = "gen_ai.provider.name"
    REQUEST_MODEL = "gen_ai.request.model"
    INPUT_TOKENS = "gen_ai.usage.input_tokens"
    OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_ID = "gen_ai.agent.id"
    TOOL_NAME = "gen_ai.tool.name"
    TOOL_CALL_ID = "gen_ai.tool.call.id"
    ERROR_TYPE = "error.type"
    SERVICE_NAME = "service.name"
    CS_AGENT_ID = "cloudsentinel.agent.id"
    CS_RUNTIME = "cloudsentinel.runtime"
    CS_TASK_ID = "cloudsentinel.task.id"
    CS_TASK_STATUS = "cloudsentinel.task.status"
    CS_PROMPT_PREVIEW = "cloudsentinel.prompt.preview"
    CS_PROMPT_HASH = "cloudsentinel.prompt.hash"
    CS_TOOL_ARGS = "cloudsentinel.tool.args"
    CS_TOOL_DECISION = "cloudsentinel.tool.decision"
    CS_TOOL_VALUE_USD = "cloudsentinel.tool.value_usd"
    # graph_node spans (LangGraph node / CrewAI step) — CloudSentinel extension, see CONTRACTS §4
    CS_NODE = "cloudsentinel.node.name"
    CS_NODE_STEP = "cloudsentinel.node.step"
    CS_NODE_FRAMEWORK = "cloudsentinel.node.framework"
    CS_NODE_STATE_DELTA = "cloudsentinel.node.state_delta"   # JSON {key: short preview} of what the node changed
    CS_NODE_NEXT = "cloudsentinel.node.next"                 # where the graph routed next (if known)


OPERATIONS = ("invoke_agent", "chat", "execute_tool", "graph_node")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Rows (CONTRACTS §5) — keep in sync with telemetry/db/schema.sql
# ─────────────────────────────────────────────────────────────────────────────
class _Row:
    def to_row(self) -> dict:
        return asdict(self)  # type: ignore[call-overload]


@dataclass
class SpanRow(_Row):
    """One normalized OTel span. Table: spans"""
    agent_id: str
    operation: str                 # invoke_agent | chat | execute_tool | graph_node
    name: str
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tool_name: str = ""
    tool_args: str = "{}"          # JSON text
    prompt_preview: str = ""
    prompt_hash: str = ""
    task_id: str = ""
    task_status: str = ""
    status: str = "ok"             # ok | error
    error_type: str = ""
    start_ts: float = field(default_factory=time.time)
    end_ts: float = 0.0
    duration_ms: float = 0.0
    detail: str = "{}"             # JSON text; graph_node: {"node","step","framework","changed":{key: preview}}
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_row(self) -> dict:
        d = asdict(self)
        d["tool_args"] = _dump(self.tool_args)
        d["detail"] = _dump(self.detail)
        return d


@dataclass
class AgentRow(_Row):
    """Registry + current state of one agent. Table: agents (upsert on agent_id)"""
    agent_id: str
    display_name: str = ""
    runtime: str = "fake"          # docker | k8s | fake | local
    runtime_id: str = ""
    state: str = "healthy"
    budget_usd: float = 0.5
    spend_usd: float = 0.0
    total_tokens: int = 0
    last_seen_ts: float = 0.0
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class MetricRow(_Row):
    """One snapshot of one agent per tick. Table: agent_metrics"""
    agent_id: str
    state: str
    tokens_per_min: int = 0
    usd_per_min: float = 0.0
    calls_per_sec: float = 0.0
    total_tokens: int = 0
    spend_usd: float = 0.0
    budget_usd: float = 0.0
    exact_repeats: int = 0
    loop_score: float = 0.0
    tool_cycle: int = 0
    memory_mb: float = 0.0
    memory_pct: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class AlertRow(_Row):
    """Table: alerts"""
    agent_id: str
    severity: str                  # info | warning | critical
    rule: str
    message: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class VerdictRow(_Row):
    """The judge's decision about one suspicious agent. Table: verdicts"""
    agent_id: str
    source: str                    # claude | gemini | fallback
    action: str                    # KILL | PAUSE | WARN | IGNORE
    confidence: float
    pattern: str
    reason: str
    suggested_fix: str = ""
    latency_ms: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ActionRow(_Row):
    """Something DONE to an agent. Table: actions"""
    agent_id: str
    action: str                    # ActionType
    actor: str                     # Actor
    reason: str
    usd_saved_estimate: float = 0.0
    tokens_saved_estimate: int = 0
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class CommandRow(_Row):
    """A request to the engine (async, executed on the next tick). Table: commands"""
    agent_id: str
    command: str                   # CommandType
    params: str = "{}"             # JSON text
    requested_by: str = "dashboard"
    reason: str = ""
    status: str = "pending"        # pending | done | failed
    result: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        d = asdict(self)
        d["params"] = _dump(self.params)
        return d


@dataclass
class MemoryRow(_Row):
    """One version of an agent's external memory. Table: agent_memory (append-only)"""
    agent_id: str
    version: int
    content: str = "{}"            # JSON object as text
    edited_by: str = "agent"       # agent | human | mcp
    reason: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        d = asdict(self)
        d["content"] = _dump(self.content)
        return d


@dataclass
class ToolCallRow(_Row):
    """A tool call that went through the gate. Table: tool_calls"""
    agent_id: str
    tool_name: str
    args: str = "{}"               # JSON text
    decision: str = "pending"      # ToolDecision
    final_args: str = "{}"         # JSON text
    decided_by: str = ""           # policy | human | mcp | timeout
    reason: str = ""
    value_usd: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)
    decided_at: str = ""

    def to_row(self) -> dict:
        d = asdict(self)
        d["args"] = _dump(self.args)
        d["final_args"] = _dump(self.final_args)
        return d


class MemoryConflict(Exception):
    """An agent tried to overwrite memory that a human/MCP changed after the agent last read it."""


# ─────────────────────────────────────────────────────────────────────────────
# 3. Executor (CONTRACTS §9) — implemented in infra/executor/, faked in shared/mocks
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RuntimeInfo:
    agent_id: str
    runtime_id: str
    runtime: str                   # docker | k8s | fake
    status: str                    # running | paused | exited
    memory_mb: float = 0.0
    memory_pct: float = 0.0


@dataclass
class ExecResult:
    ok: bool
    message: str = ""


class Executor(Protocol):
    def list_agents(self) -> list[RuntimeInfo]: ...
    def pause(self, agent_id: str) -> ExecResult: ...
    def resume(self, agent_id: str) -> ExecResult: ...
    def kill(self, agent_id: str) -> ExecResult: ...
    def restart(self, agent_id: str) -> ExecResult: ...
    def go_rogue(self, agent_id: str, kind: str) -> ExecResult: ...


# ─────────────────────────────────────────────────────────────────────────────
# 4. API view models (CONTRACTS §6)
# ─────────────────────────────────────────────────────────────────────────────
def agent_view(agent: dict, metric: Optional[dict], verdict: Optional[dict]) -> dict:
    """Build the AgentView JSON from an agents row + latest metric + latest verdict."""
    m = metric or {}
    return {
        "agent_id": agent["agent_id"],
        "display_name": agent.get("display_name") or agent["agent_id"],
        "runtime": agent.get("runtime", ""),
        "state": agent.get("state", "healthy"),
        "budget_usd": float(agent.get("budget_usd") or 0),
        "spend_usd": float(agent.get("spend_usd") or 0),
        "total_tokens": int(agent.get("total_tokens") or 0),
        "tokens_per_min": int(m.get("tokens_per_min") or 0),
        "usd_per_min": float(m.get("usd_per_min") or 0),
        "calls_per_sec": float(m.get("calls_per_sec") or 0),
        "exact_repeats": int(m.get("exact_repeats") or 0),
        "loop_score": float(m.get("loop_score") or 0),
        "tool_cycle": bool(m.get("tool_cycle") or 0),
        "memory_pct": float(m.get("memory_pct") or 0),
        "last_verdict": verdict,
        "updated_at": agent.get("updated_at", ""),
    }


ROI_FORMULA = ("KILL/PAUSE: saved = $/min at the moment of action × horizon (how long a runaway agent would "
               "burn before a human notices). TOOL_DENY: saved = value at stake. "
               "TOOL_REWRITE: saved = value at stake × (1 − new amount / old amount).")
