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
                     "MEMORY_EDIT", "TOOL_ALLOW", "TOOL_DENY", "TOOL_REWRITE", "AUTO_HEAL",
                     "POLICY_RELOAD", "TOOL_INJECTION_DENY", "TOOL_AUTO_ALLOW",
                     "THROTTLE", "DOWNGRADE"]
ACTION_TYPES = ("KILL", "PAUSE", "RESUME", "RESTART", "WARN", "SET_BUDGET",
                "MEMORY_EDIT", "TOOL_ALLOW", "TOOL_DENY", "TOOL_REWRITE", "AUTO_HEAL",
                "POLICY_RELOAD", "TOOL_INJECTION_DENY", "TOOL_AUTO_ALLOW",
                "THROTTLE", "DOWNGRADE")

# The degradation ladder (CONTRACTS §8, B4): the order a runaway agent is
# stepped down in, from the gentlest to the last resort.
#
# The order is the whole point. A throttle costs the agent almost nothing and
# a kill costs it everything, so the ladder starts gentle and gets harsher
# only as the gentler steps fail. **A step never skips a rung** — an agent
# that has not been throttled is not downgraded, because a downgrade is a
# bigger promise than a throttle and deserves the smaller one's evidence
# first.
DEGRADATION_LADDER = ("THROTTLE", "DOWNGRADE", "PAUSE", "KILL")

Actor = Literal["rules", "claude", "gemini", "fallback", "human", "policy", "mcp",
                "brain:autoheal", "brain:toolrisk"]

CommandType = Literal["KILL", "PAUSE", "RESUME", "RESTART", "GO_ROGUE", "SET_BUDGET"]
COMMAND_TYPES = ("KILL", "PAUSE", "RESUME", "RESTART", "GO_ROGUE", "SET_BUDGET")

Pattern = Literal["infinite_loop", "semantic_loop", "token_spike", "memory_leak", "bad_tool_call",
                  "prompt_injection", "unsafe_tool_input", "legitimate_burst", "other"]
PATTERNS = ("infinite_loop", "semantic_loop", "token_spike", "memory_leak", "bad_tool_call",
            "prompt_injection", "unsafe_tool_input", "legitimate_burst", "other")

ToolDecision = Literal["pending", "allow", "deny", "rewrite", "timeout"]
TOOL_DECISIONS = ("pending", "allow", "deny", "rewrite", "timeout")

# Auto-heal (CONTRACTS §7): the judge proposes a patch; a high-confidence one is applied
# automatically, anything less lands in the approvals inbox for a human.
HealKind = Literal["memory_patch", "tool_policy"]
HEAL_KINDS = ("memory_patch", "tool_policy")

HealStatus = Literal["pending", "applied", "rejected", "expired"]
HEAL_STATUSES = ("pending", "applied", "rejected", "expired")

HealDecision = Literal["apply", "reject"]
HEAL_DECISIONS = ("apply", "reject")

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
    # The brain's own verdict spans (A15) — CloudSentinel extension, see CONTRACTS §4.
    # The brain emits these on the *agent's* trace, so an operator watching the agent
    # in Phoenix sees the verdict on the same trace as the behaviour that caused it.
    CS_VERDICT_ACTION = "cloudsentinel.verdict.action"        # PAUSE | KILL | WARN | ...
    CS_VERDICT_SOURCE = "cloudsentinel.verdict.source"        # claude | gemini | fallback
    CS_VERDICT_CONFIDENCE = "cloudsentinel.verdict.confidence"
    CS_VERDICT_REASON = "cloudsentinel.verdict.reason"
    CS_LOOP_SCORE = "cloudsentinel.loop.score"                # the semantic loop score, 0..1
    CS_EXACT_REPEATS = "cloudsentinel.loop.exact_repeats"     # the same prompt repeated N times
    # The verified auto-heal flow (B1) — CloudSentinel extension, see CONTRACTS §4.
    # The shadow dry-run's verdict and the decision it produced ride on the same
    # `cs_verdict` span as the verdict itself, as a separate span event.
    CS_HEAL_SHADOW_VERDICT = "cloudsentinel.heal.shadow_verdict"   # healthy | still_bad | no_opinion
    CS_HEAL_APPLIED = "cloudsentinel.heal.applied"                 # true = the patch was applied
    CS_HEAL_CONFIDENCE = "cloudsentinel.heal.confidence"           # the judge's confidence, 0..1
    CS_HEAL_LOOP_SCORE_BEFORE = "cloudsentinel.heal.loop_score_before"
    CS_HEAL_LOOP_SCORE_AFTER = "cloudsentinel.heal.loop_score_after"
    CS_HEAL_REASON = "cloudsentinel.heal.reason"                   # why it was applied or withheld


OPERATIONS = ("invoke_agent", "chat", "execute_tool", "graph_node", "cs_verdict")


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
    operation: str                 # invoke_agent | chat | execute_tool | graph_node | cs_verdict
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
    baseline: str = "{}"            # JSON text; adaptive per-agent limits (A4)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        d = asdict(self)
        d["baseline"] = _dump(self.baseline)
        return d


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
class InjectionVerdict:
    """
    The result of scoring one piece of agent text or one tool call (CONTRACTS §11, added 8 Nov).

    `score` is 0..1. `reasons` are short, human-readable — they say WHICH signal fired, so the
    dashboard and the judge can explain a deny without reading the source.
    """
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)   # the signal names, for counting

    @property
    def hit(self) -> bool:
        return self.score > 0.0

    def to_dict(self) -> dict:
        return {"score": round(self.score, 3), "reasons": list(self.reasons),
                "signals": list(self.signals)}


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


@dataclass
class HealProposalRow(_Row):
    """
    A patch the judge proposes for a malfunctioning agent (CONTRACTS §7). Table: heal_proposals

    `kind` says what the patch touches:
      - `memory_patch` — `patch` is `{"memory": [{"op": "set"|"remove", "key": str, "value": any}]}`
      - `tool_policy` — `patch` is `{"tool_policy": {"tool": str, "action": "deny"|"approval"}}`

    `base_version` is the agent_memory version the judge saw. If the memory moved on since,
    the proposal is stale and becomes `expired` rather than overwriting newer work.

    `status`:
      - `pending`  — waiting for a human (or waiting for a higher confidence)
      - `applied`  — the patch was written
      - `rejected` — a human said no
      - `expired`  — the base version moved on, so the patch no longer applies
    """
    agent_id: str
    kind: str = "memory_patch"
    patch: str = "{}"              # JSON text
    confidence: float = 0.0
    status: str = "pending"        # HealStatus
    verdict_id: int = 0
    base_version: int = 0
    reason: str = ""
    decided_by: str = ""           # human | mcp | brain:autoheal
    decided_at: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_row(self) -> dict:
        d = asdict(self)
        d["patch"] = _dump(self.patch)
        return d


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
    baseline = agent.get("baseline")
    if isinstance(baseline, str):
        baseline = load_json(baseline)
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
        "baseline": baseline if isinstance(baseline, dict) else {},
        "last_verdict": verdict,
        "updated_at": agent.get("updated_at", ""),
    }


ROI_FORMULA = ("KILL/PAUSE: saved = $/min at the moment of action × horizon (how long a runaway agent would "
               "burn before a human notices). TOOL_DENY: saved = value at stake. "
               "TOOL_REWRITE: saved = value at stake × (1 − new amount / old amount).")


# ─────────────────────────────────────────────────────────────────────────────
# 5. The incident explanation (CONTRACTS §6, A13)
# ─────────────────────────────────────────────────────────────────────────────
# The explanation is built here, in the contract folder, because the **mock API and the
# real API must say the same thing**. The mock (dashboard development) and the brain
# (production) live in different folders, and a golden-text test compares them. If the
# text were written twice — once in `shared/mocks/` and once in `brain/` — the two would
# drift, and the golden test would be testing the mock against itself.
#
# It is deliberately deterministic: no key, no network, no clock of its own. The same
# agent and the same events always produce the same paragraph. That is what makes it
# testable and what makes it safe to cache. The optional Claude polish is added by the
# caller (the brain), never here.

# The words a verdict's action is described with, in the summary.
_ACTION_WORDS = {
    "KILL": "killed",
    "PAUSE": "paused",
    "WARN": "warned about",
    "IGNORE": "left alone",
}


def explain_event(kind: str, ts: float, title: str, detail: str = "") -> dict:
    """One link in the story. The shape is the contract, so it is built here."""
    return {"kind": kind, "ts": round(float(ts or 0), 1), "title": str(title), "detail": str(detail)}


def explain_summary(agent_id: str, state: str, events: list[dict], spend_usd: float = 0.0,
                    budget_usd: float = 0.0, saved_usd: float = 0.0) -> str:
    """
    The plain-English paragraph: what happened to this agent, and why.

    Deterministic on purpose — the same events always produce the same words, so a
    golden-text test can pin them and a dashboard can cache them.
    """
    state = (state or "unknown").upper()
    spend = float(spend_usd or 0.0)
    budget = float(budget_usd or 0.0)

    if not events:
        return (f"{agent_id} is {state}. Nothing happened in this window: no alert fired, no judge "
                f"verdict was reached, and no action was taken.")

    # The last thing that happened to it is the outcome.
    outcome = events[-1]
    kind = outcome.get("kind")
    if kind == "action":
        verb = _ACTION_WORDS.get(str(outcome.get("title", "")).upper(),
                                 str(outcome.get("title", "acted on")))
        head = f"{agent_id} is {state}: the brain {verb} it."
    elif kind == "verdict":
        action = str(outcome.get("title", "")).upper()
        head = (f"{agent_id} is {state}: the judge decided {action}, "
                f"and the breaker did not act on it.")
    elif kind == "alert":
        head = f"{agent_id} is {state}: the rules flagged it and the judge has not answered yet."
    elif kind == "heal":
        head = f"{agent_id} is {state}: a fix was applied and it is back at work."
    else:
        head = f"{agent_id} is {state}."

    counts: dict[str, int] = {}
    for e in events:
        k = str(e.get("kind"))
        counts[k] = counts.get(k, 0) + 1
    parts = [f"{n} {k}{'s' if n != 1 else ''}" for k, n in sorted(counts.items()) if k in
             ("alert", "verdict", "action", "heal")]
    if parts:
        head += " In this window there were " + ", ".join(parts) + "."

    if budget > 0:
        head += f" It has spent ${spend:.4f} of its ${budget:.2f} budget."
    if saved_usd > 0:
        head += f" That intervention saved about ${saved_usd:.2f}."

    # The reason the judge gave, when there was one.
    for e in reversed(events):
        if e.get("kind") == "verdict" and e.get("detail"):
            head += f" The judge said: {e['detail']}"
            break
    return head


def explain_report(agent_id: str, state: str, events: list[dict], minutes: float = 10.0,
                   spend_usd: float = 0.0, budget_usd: float = 0.0, saved_usd: float = 0.0) -> dict:
    """
    The whole `ExplainReport` (CONTRACTS §6).

    `polished_summary` is always `None` here: the Claude polish is the brain's job, and it
    must never be able to break the endpoint. A client renders `polished_summary` when it
    is there and falls back to `summary` when it is `None`.
    """
    events = list(events or [])
    counts = {"alerts": 0, "verdicts": 0, "actions": 0, "heals": 0}
    for e in events:
        k = str(e.get("kind"))
        if k == "alert":
            counts["alerts"] += 1
        elif k == "verdict":
            counts["verdicts"] += 1
        elif k == "action":
            counts["actions"] += 1
        elif k == "heal":
            counts["heals"] += 1
    outcome = None
    for e in reversed(events):
        if e.get("kind") == "action":
            outcome = str(e.get("title") or "") or None
            break
    if outcome is None:
        for e in reversed(events):
            if e.get("kind") == "verdict":
                outcome = str(e.get("title") or "") or None
                break
    return {
        "agent_id": agent_id,
        "state": state or "unknown",
        "minutes": float(minutes),
        "summary": explain_summary(agent_id, state or "unknown", events, spend_usd, budget_usd, saved_usd),
        "polished_summary": None,
        "events": events,
        "counts": counts,
        "outcome": outcome,
        "cost": {"spend_usd": float(spend_usd or 0.0), "budget_usd": float(budget_usd or 0.0),
                 "saved_usd": float(saved_usd or 0.0)},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5b. The incident postmortem (CONTRACTS §6, B2)
# ─────────────────────────────────────────────────────────────────────────────
# **What an incident is.** There is no incident table. An incident *is* an alert:
# the moment the brain flagged an agent and said "something is wrong here". The
# verdict that followed, the action that was taken and the heal that fixed it are
# all part of *that* incident. So the incident id is the alert id, and
# `GET /v1/incidents/{id}/postmortem` looks the alert up and tells its whole story.
#
# **The shape is the contract.** The builder is here, in the contract folder, for
# the same reason the explain builder is: the mock API and the real API must say
# the same thing, and a golden test compares them. Written twice, they would drift.
#
# **Deterministic.** No key, no network, no clock of its own. The same alert and
# the same store always produce the same postmortem — which is what makes it
# testable, and what makes it safe to attach to a ticket.

# The kinds of event a timeline holds, in the order they can happen. The order is
# the point: an alert cannot precede the verdict that caused it.
POSTMORTEM_EVENT_KINDS = ("evidence", "alert", "verdict", "action", "heal")

# The actions that stopped a runaway, and so saved money (CONTRACTS §8, ROI_FORMULA).
POSTMORTEM_SAVING_ACTIONS = ("KILL", "PAUSE", "TOOL_DENY", "TOOL_REWRITE")


def postmortem_event(kind: str, ts: float, title: str, detail: str = "",
                     ref: Optional[str] = None) -> dict:
    """One moment in an incident's timeline.

    `ref` is the id of the row or span this moment came from — the evidence. A
    timeline whose entries cannot be traced back to a row is a story, not a record.
    """
    return {"kind": str(kind), "ts": round(float(ts or 0), 1), "title": str(title),
            "detail": str(detail), "ref": (str(ref) if ref else None)}


def postmortem_root_cause(rule: str, pattern: str, reason: str, detector: str = "rules") -> dict:
    """
    Why it happened — in the words of the system that noticed.

    The root cause names the rule that fired and the pattern the judge saw. It is
    never "unknown": if the brain could not say why, it says *that* — but it always
    says which rule fired, because the rule is what the detectors measured.
    """
    rule = str(rule or "").strip()
    pattern = str(pattern or "").strip()
    reason = str(reason or "").strip()
    # A rule that fired is a root cause even when the judge said nothing: the rule
    # *is* the pattern the detectors measured. So the pattern falls back to the rule,
    # and only a postmortem with neither can honestly say "unknown".
    if rule and pattern:
        headline = f"{rule} — {pattern}"
    elif rule:
        pattern = rule
        headline = rule
    elif pattern:
        headline = pattern
    else:
        headline = "unknown"
    return {"rule": rule or "unknown", "pattern": pattern or "unknown",
            "detector": str(detector or "rules"), "headline": headline, "reason": reason}


def postmortem_report(incident_id: int, agent_id: str, root_cause: dict, timeline: list[dict],
                      evidence: list[dict], money: dict, timings: dict,
                      resolution: str = "") -> dict:
    """
    The whole `PostmortemReport` (CONTRACTS §6).

    `timeline` is sorted by time, oldest first. `evidence` holds the real span ids
    — not a summary of them — so a reader can pull the exact spans out of Phoenix.

    `timings` holds the two numbers an operator asks for first:
      - `time_to_detect_seconds`: from the first evidence to the alert
      - `time_to_heal_seconds`: from the alert to the action that fixed it
    A number that cannot be measured is `None`, never a made-up zero — "0.0" and
    "we do not know" are different facts and only one of them is true.
    """
    timeline = sorted(list(timeline or []), key=lambda e: float(e.get("ts") or 0))
    evidence = list(evidence or [])
    money = dict(money or {})
    timings = dict(timings or {})
    return {
        "incident_id": int(incident_id),
        "agent_id": str(agent_id or ""),
        "root_cause": dict(root_cause or {}),
        "timeline": timeline,
        "evidence": evidence,
        "money": {
            "usd_saved": float(money.get("usd_saved") or 0.0),
            "tokens_saved": int(money.get("tokens_saved") or 0),
            "spend_usd": float(money.get("spend_usd") or 0.0),
            "formula": str(money.get("formula") or ROI_FORMULA),
        },
        "timings": {
            "time_to_detect_seconds": timings.get("time_to_detect_seconds"),
            "time_to_heal_seconds": timings.get("time_to_heal_seconds"),
            "detected_at": timings.get("detected_at"),
            "healed_at": timings.get("healed_at"),
        },
        "resolution": str(resolution or ""),
    }


def postmortem_markdown(report: dict) -> str:
    """
    The same postmortem, as markdown.

    The numbers must be the numbers in the JSON — a markdown that says "$0.12 saved"
    when the JSON says 0.12 is a report nobody can trust. So this reads the JSON and
    writes it out; it never recomputes anything.
    """
    if not report:
        return "# No incident\n\nThere is no incident to report.\n"

    root = report.get("root_cause") or {}
    money = report.get("money") or {}
    timings = report.get("timings") or {}

    def _seconds(value) -> str:
        if value is None:
            return "not measured"
        return f"{float(value):.1f}s"

    lines = [
        f"# Incident {report.get('incident_id')} — agent `{report.get('agent_id')}`",
        "",
        "## Root cause",
        "",
        f"- **Rule**: {root.get('rule', 'unknown')}",
        f"- **Pattern**: {root.get('pattern', 'unknown')}",
        f"- **Detected by**: {root.get('detector', 'rules')}",
    ]
    if root.get("reason"):
        lines.append(f"- **Why**: {root['reason']}")

    lines += [
        "",
        "## Timeline",
        "",
    ]
    timeline = report.get("timeline") or []
    if timeline:
        for e in timeline:
            ref = f" (`{e['ref']}`)" if e.get("ref") else ""
            detail = f" — {e['detail']}" if e.get("detail") else ""
            lines.append(f"- `{e.get('ts', 0):.1f}` **{e.get('kind', '?')}**: {e.get('title', '')}{ref}{detail}")
    else:
        lines.append("- _No events._")

    lines += [
        "",
        "## Evidence",
        "",
    ]
    evidence = report.get("evidence") or []
    if evidence:
        lines.append("| span_id | trace_id | operation | start_ts |")
        lines.append("|---|---|---|---|")
        for s in evidence:
            lines.append(f"| `{s.get('span_id', '')}` | `{s.get('trace_id', '')}` | "
                         f"{s.get('operation', '')} | {s.get('start_ts', 0)} |")
    else:
        lines.append("_No spans._")

    lines += [
        "",
        "## Money",
        "",
        f"- **Saved**: ${float(money.get('usd_saved') or 0.0):.4f} "
        f"({int(money.get('tokens_saved') or 0):,} tokens)",
        f"- **Spent**: ${float(money.get('spend_usd') or 0.0):.4f}",
        f"- **Formula**: {money.get('formula', '')}",
        "",
        "## Timings",
        "",
        f"- **Time to detect**: {_seconds(timings.get('time_to_detect_seconds'))}",
        f"- **Time to heal**: {_seconds(timings.get('time_to_heal_seconds'))}",
        "",
    ]
    if report.get("resolution"):
        lines += ["## Resolution", "", report["resolution"], ""]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# 5c. The budget hierarchy and the degradation ladder (CONTRACTS §8, B4)
# ─────────────────────────────────────────────────────────────────────────────
# One agent cannot spend the whole fleet's money. The budget is a tree —
# org → team → agent — and every level is the sum of the level below it. So
# an agent that runs away eats its *own* share first, and the org's money is
# still there for the other agents.
#
# The forecast answers the question an operator asks at 3 AM: "how long have
# I got?" — and it answers it only when it can. **A burn rate of zero has no
# forecast**: "exhausted in 0 minutes" is a lie, and "exhausted in infinity"
# is not a number anybody can put in a dashboard. So the answer is `null`, and
# the sentence it becomes says nothing rather than something false.
#
# The ladder is the order a runaway agent is stepped down in, and it never
# skips a rung: throttle → downgrade → pause → kill.

# The levels of the budget tree, from the widest to the narrowest.
BUDGET_LEVELS = ("org", "team", "agent")


def budget_forecast(budget_usd: float, spend_usd: float, usd_per_min: float,
                    horizon_minutes: float = 60.0) -> dict:
    """
    "This budget is exhausted in X minutes" — or nothing, when it cannot be told.

    The forecast is the burn rate (`usd_per_min`) times forward until the
    remaining money is gone. Two facts make it honest:

    - **a burn rate of zero has no forecast** — nothing is being spent, so
      nothing will be exhausted, and "in 0 minutes" would be a lie;
    - **a budget that is already gone has already been exhausted** — the
      forecast is 0 minutes, not a negative number.

    `remaining_usd` is what is left, and it is never negative: an over-budget
    agent has 0 left, not -$3.
    """
    budget_usd = float(budget_usd or 0.0)
    spend_usd = float(spend_usd or 0.0)
    usd_per_min = float(usd_per_min or 0.0)
    horizon_minutes = float(horizon_minutes or 0.0)

    remaining = max(0.0, budget_usd - spend_usd)
    if usd_per_min <= 0:
        minutes = None
        sentence = ""
    else:
        minutes = round(remaining / usd_per_min, 1)
        if remaining <= 0:
            sentence = "the budget is already exhausted"
        else:
            sentence = f"exhausted in {minutes:.0f} min"
    return {
        "remaining_usd": round(remaining, 4),
        "usd_per_min": round(usd_per_min, 4),
        "minutes_to_exhausted": minutes,
        "horizon_minutes": horizon_minutes,
        "sentence": sentence,
        "exhausted_within_horizon": (minutes is not None and minutes <= horizon_minutes),
    }


def budget_node(level: str, node_id: str, budget_usd: float, spend_usd: float,
                children: Optional[list] = None, forecast: Optional[dict] = None) -> dict:
    """One node of the budget tree: org, team or agent."""
    return {
        "level": str(level),
        "id": str(node_id),
        "budget_usd": round(float(budget_usd or 0.0), 4),
        "spend_usd": round(float(spend_usd or 0.0), 4),
        "remaining_usd": round(max(0.0, float(budget_usd or 0.0) - float(spend_usd or 0.0)), 4),
        "children": list(children or []),
        "forecast": dict(forecast or {}),
    }


def budget_report(org: dict, teams: Optional[list] = None, agents: Optional[list] = None,
                  as_of: Optional[float] = None) -> dict:
    """
    The whole `BudgetReport` — the budget tree, top to bottom.

    The tree is the point: **the org's budget is the sum of the teams', and a
    team's is the sum of its agents'**. So one runaway agent cannot eat the
    fleet's money — it eats its own share, and the tree says so out loud.
    """
    teams = list(teams or [])
    agents = list(agents or [])
    return {
        "org": dict(org or {}),
        "teams": teams,
        "agents": agents,
        "as_of": as_of,
    }


def degradation_plan(current_step: Optional[str] = None,
                     applied: Optional[list] = None) -> dict:
    """
    Where an agent stands on the ladder, and what comes next.

    `applied` is the list of rungs already gone through. The plan says which
    rung comes next and — just as importantly — **which rungs must not be
    skipped**: an agent that has not been throttled is not downgraded.
    """
    applied = [str(a) for a in (applied or []) if str(a) in DEGRADATION_LADDER]
    if current_step is not None and str(current_step) in DEGRADATION_LADDER:
        # "The agent is at PAUSE" means the ladder was walked *up to and
        # including* PAUSE — you cannot be paused without having been
        # throttled and downgraded first. So the rungs below it are applied
        # too, and the next rung is the one after PAUSE.
        through = DEGRADATION_LADDER.index(str(current_step)) + 1
        applied = list(DEGRADATION_LADDER[:through])
    index = len(applied)
    next_step = DEGRADATION_LADDER[index] if index < len(DEGRADATION_LADDER) else None
    return {
        "ladder": list(DEGRADATION_LADDER),
        "applied": applied,
        "next_step": next_step,
        "exhausted": next_step is None,
        "skipped": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. The learned tool risk (CONTRACTS §6, A14)
# ─────────────────────────────────────────────────────────────────────────────
# A human approves the same refund five times a day. The fifth time, asking again
# is friction, not safety: the person has already answered the same question five
# times. A14 learns that — and records *why* it decided on its own.
#
# The builder is here, in the contract folder, for the same reason the explain
# builder is: the mock and the real API must say the same thing.

# How many human approvals of the *identical* call are needed before the brain
# stops asking. Five is the number the task names.
TOOL_RISK_AUTO_APPROVE_AFTER = 5


def tool_risk_signature(tool_name: str, args: Any) -> str:
    """
    The identity of a tool call: the tool plus its arguments, canonically.

    Two calls with the same arguments in a different order are the same call —
    a refund of 500 BDT for order 4471 is a refund of 500 BDT for order 4471,
    however the JSON was written. The signature is what the approvals are counted
    against, so it must not depend on the order of the keys.
    """
    payload = json.dumps(args if isinstance(args, dict) else {}, sort_keys=True, default=str)
    return f"{str(tool_name or '').strip()}:{payload}"


def tool_risk_entry(agent_id: str, tool_name: str, args: Any, approvals: int, denials: int,
                    threshold: int = TOOL_RISK_AUTO_APPROVE_AFTER) -> dict:
    """One (agent, tool, args) — how many times a human said yes, and no."""
    approvals = int(approvals or 0)
    denials = int(denials or 0)
    return {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "args": args if isinstance(args, dict) else {},
        "signature": tool_risk_signature(tool_name, args),
        "approvals": approvals,
        "denials": denials,
        "threshold": int(threshold),
        # The one thing a client needs: may this call go through without a human?
        "auto_approved": approvals >= int(threshold),
        # Why the score is what it is — a client should never have to guess.
        "reason": (f"{approvals} human approval(s) of this exact call; "
                   f"auto-approve after {int(threshold)}"
                   if approvals >= int(threshold)
                   else f"{approvals} human approval(s) of this exact call; "
                        f"{int(threshold) - approvals} more needed to auto-approve"),
    }


def tool_risk_view(entries: list[dict], threshold: int = TOOL_RISK_AUTO_APPROVE_AFTER) -> dict:
    """The whole `ToolRiskReport` (CONTRACTS §6)."""
    entries = list(entries or [])
    return {
        "entries": entries,
        "counts": {
            "entries": len(entries),
            "auto_approved": sum(1 for e in entries if e.get("auto_approved")),
            "denied": sum(1 for e in entries if int(e.get("denials") or 0) > 0),
        },
        "threshold": int(threshold),
    }


def tool_risk_from_history(calls: list[dict], threshold: int = TOOL_RISK_AUTO_APPROVE_AFTER) -> list[dict]:
    """
    Count the human answers in the tool-call history, grouped by the exact call.

    Only a **human** answer counts. A `policy` allow is the rules doing their job, and
    an `mcp` answer is another agent's opinion — neither is a person saying "yes, this
    is fine", so neither may teach the brain to stop asking.

    A **denial counts against** the score: a person who refused this call three times
    has said something about it, and the score must not go up because a fifth approval
    happened to arrive. The entry keeps both counts so a client can show the whole
    history, and the auto-approve decision needs the approvals to outweigh the denials.
    """
    tally: dict[str, dict] = {}
    for call in calls or []:
        if not isinstance(call, dict):
            continue
        decided_by = str(call.get("decided_by") or "")
        if decided_by != "human":
            continue
        decision = str(call.get("decision") or "")
        if decision not in ("allow", "deny"):
            continue
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        agent_id = str(call.get("agent_id") or "")
        tool_name = str(call.get("tool_name") or "")
        signature = tool_risk_signature(tool_name, args)
        key = f"{agent_id}\x00{signature}"
        row = tally.setdefault(key, {
            "agent_id": agent_id, "tool_name": tool_name, "args": args,
            "signature": signature, "approvals": 0, "denials": 0,
        })
        if decision == "allow":
            row["approvals"] += 1
        else:
            row["denials"] += 1
    entries = []
    for row in tally.values():
        entry = tool_risk_entry(row["agent_id"], row["tool_name"], row["args"],
                                row["approvals"], row["denials"], threshold)
        # A denial is a veto: a call a human refused is never auto-approved, however
        # many times somebody else later said yes. The counts stay — a client must be
        # able to show that five people said yes and one said no.
        if row["denials"] > 0:
            entry["auto_approved"] = False
            entry["reason"] = (f"{row['approvals']} human approval(s) and {row['denials']} denial(s) of "
                               f"this exact call; a denial vetoes auto-approve")
        entries.append(entry)
    entries.sort(key=lambda e: (-e["approvals"], e["agent_id"], e["tool_name"]))
    return entries
