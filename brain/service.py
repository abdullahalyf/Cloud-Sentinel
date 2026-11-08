"""
Operations shared by the C2 API, the tool gate and the fake fleet. Each function is small and
works only through the Store, so the API stays thin and everything is testable without HTTP.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Optional

from brain.policy import Policy
from shared.contracts import (COMMAND_TYPES, ROGUE_KINDS, ActionRow, AlertRow, CommandRow, ToolCallRow,
                              agent_view, load_json)


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# How strict a decision is. The stricter of two gates wins.
# "" means "this gate had nothing to say" — it must lose to any real decision, including allow.
_SEVERITY = {"": -1, "allow": 0, "approval": 1, "deny": 2}


def _severity(action: str) -> int:
    return _SEVERITY.get(action, 1)


class InjectionGate:
    """
    The injection part of the tool gate (A6, CONTRACTS §11a).

    It scores a tool call's arguments once and turns the score into a decision:
    a score at or above the deny threshold denies the call, a score at or above the approval
    threshold leaves it pending for a human, and anything lower is left to the policy.

    The gate also records what it saw, so the dashboard can show why a call was blocked.
    """

    def __init__(self, deny_threshold: float = 0.8, approval_threshold: float = 0.5,
                 allowed_hosts: str = "", enabled: bool = True):
        self.deny_threshold = deny_threshold
        self.approval_threshold = approval_threshold
        self.allowed_hosts = allowed_hosts
        self.enabled = enabled

    def check(self, tool_name: str, args: dict) -> tuple[str, str]:
        """(action, reason) for one tool call. "allow" and an empty reason mean nothing fired."""
        if not self.enabled:
            return "", ""
        from brain.injection import gate_decision, score_tool_args

        verdict = score_tool_args(tool_name, args, self.allowed_hosts)
        action = gate_decision(verdict.score, self.deny_threshold, self.approval_threshold)
        if action == "allow":
            return "", ""
        return action, f"injection score {verdict.score:.2f}: " + "; ".join(verdict.reasons)


# Allowed actor values (CONTRACTS §5). Anything else is a caller bug → 400, not a silent bad audit row.
REQUESTERS = ("dashboard", "mcp", "terminal", "eval")
EDITORS = ("agent", "human", "mcp")
DECIDERS = ("human", "mcp")
MAX_MEMORY_BYTES = 64_000      # agent memory is a small JSON object, not a file store
MAX_AGENT_ID = 64


def check_agent_id(agent_id: str) -> str:
    agent_id = (agent_id or "").strip()
    if not agent_id or len(agent_id) > MAX_AGENT_ID:
        raise ApiError(400, f"agent_id must be 1–{MAX_AGENT_ID} characters")
    return agent_id


def money(value) -> float:
    """value_usd from an agent: missing, negative, NaN or inf all become 0 (it only feeds the ROI estimate)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) and v > 0 else 0.0


def actor_for(requested_by: str) -> str:
    return "mcp" if requested_by == "mcp" else "human"


# ── commands ──
def post_command(store, agent_id: str, command: str, params: Optional[dict], requested_by: str,
                 reason: str) -> int:
    agent_id = check_agent_id(agent_id)
    command = (command or "").strip().upper()
    if requested_by not in REQUESTERS:
        raise ApiError(400, f"requested_by must be one of {', '.join(REQUESTERS)}")
    if command not in COMMAND_TYPES:
        raise ApiError(400, f"unknown command {command}; use one of {', '.join(COMMAND_TYPES)}")
    params = params or {}
    if command == "SET_BUDGET":
        try:
            budget = float(params.get("budget_usd", -1))
            if not math.isfinite(budget) or budget <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ApiError(400, "SET_BUDGET needs params.budget_usd > 0")
    if command == "GO_ROGUE" and params.get("kind", "paraphrase_loop") not in ROGUE_KINDS:
        raise ApiError(400, f"kind must be one of {ROGUE_KINDS}")
    return store.insert_command(CommandRow(agent_id, command, params, requested_by, reason))


# ── memory ──
def save_memory(store, agent_id: str, content: dict, edited_by: str, reason: str,
                base_version: Optional[int], injection: Optional[InjectionGate] = None) -> dict:
    from shared.contracts import MemoryConflict

    agent_id = check_agent_id(agent_id)
    if not isinstance(content, dict):
        raise ApiError(400, "memory content must be a JSON object")
    if edited_by not in EDITORS:
        raise ApiError(400, f"edited_by must be one of {', '.join(EDITORS)}")
    if base_version is not None and base_version < 0:
        raise ApiError(400, "base_version must be >= 0")
    if len(json.dumps(content, default=str)) > MAX_MEMORY_BYTES:
        raise ApiError(400, f"memory content is larger than {MAX_MEMORY_BYTES} bytes")
    # A poisoned memory is a belief the agent will keep. The write still happens — the memory may
    # be a legitimate instruction — but a human is told about it (A6).
    if injection is not None:
        _alert_on_poisoned_memory(store, agent_id, content, injection)
    try:
        row = store.write_memory(agent_id, content, edited_by, reason, base_version)
    except MemoryConflict as exc:
        raise ApiError(409, str(exc))
    if edited_by in ("human", "mcp"):
        store.insert_action(ActionRow(agent_id, "MEMORY_EDIT", edited_by, reason or "memory edited"))
    return row


def _alert_on_poisoned_memory(store, agent_id: str, content: dict, gate: InjectionGate) -> None:
    """Raise an alert when a memory write carries an instruction that tries to bend the rules."""
    from brain.injection import MEMORY_ALERT_SCORE, score_text

    if not gate.enabled:
        return
    blob = json.dumps(content, ensure_ascii=False, default=str)
    verdict = score_text(blob)
    if verdict.score < MEMORY_ALERT_SCORE:
        return
    store.insert_alert(AlertRow(agent_id, "warning", "injection_detected",
                                f"memory write scored {verdict.score:.2f} for injection: "
                                + "; ".join(verdict.reasons)))


# ── tool gate ──
def _amount(args: dict) -> Optional[float]:
    for key in ("amount", "value", "quantity", "recipients"):
        try:
            return float(args[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def saved_by_tool_decision(decision: str, args: dict, final_args: dict, value_usd: float) -> float:
    """Money kept safe by a deny / rewrite (CONTRACTS §8)."""
    if decision in ("deny", "timeout"):
        return round(value_usd, 4)
    if decision == "rewrite":
        old, new = _amount(args), _amount(final_args)
        if old and new is not None and old > 0:
            return round(value_usd * max(0.0, 1 - new / old), 4)
    return 0.0


def request_tool_call(store, policy: Policy, agent_id: str, tool_name: str, args: dict,
                      value_usd: Optional[float], injection: Optional[InjectionGate] = None) -> dict:
    """
    Called by the SDK before running a tool. Policy decides now, or leaves it pending for a human.

    Two gates, in this order:
      1. the injection scorer (A6) — an argument that carries an attack is denied or escalated
      2. the policy — budgets and the tool rules

    The injection gate runs FIRST on purpose: a policy rule that allows `run_sql` should not let
    a `; DROP TABLE` through just because the policy had no rule for it.

    A third thing happens last (A14): a call the policy would have *held for approval* is let
    through when a human has already approved that exact call enough times. It never touches a
    deny — the injection gate and the policy's deny rules still win.
    """
    agent_id = check_agent_id(agent_id)
    tool_name = (tool_name or "").strip()
    if not tool_name:
        raise ApiError(400, "tool_name is required")
    args = args if isinstance(args, dict) else {}
    action, reason = "", ""
    if injection is not None:
        action, reason = injection.check(tool_name, args)
    try:
        policy_action, policy_reason = policy.decide_tool(tool_name, args)
    except Exception as exc:  # a broken rule must fail SAFE: a human decides
        policy_action, policy_reason = "approval", f"policy error ({exc}); needs a human"
    # The stricter of the two wins: a deny beats an approval, an approval beats an allow.
    if _severity(action) >= _severity(policy_action):
        action, reason = action, reason or policy_reason
    else:
        action, reason = policy_action, policy_reason
    agent = store.get_agent(agent_id)
    if agent and agent.get("state") in ("paused", "killed"):
        # second layer: even if the container could not be frozen, a tripped agent gets no tools
        action, reason = "deny", f"agent is {agent['state']} by CloudSentinel"
    # A14: the learned tool risk. It only ever turns an *approval* into an allow, so a
    # deny above is untouched. The auto-approval is written to the audit log below.
    learned_entry = None
    if action == "approval":
        from brain import tool_risk

        learned_entry = tool_risk.is_auto_approved(store, agent_id, tool_name, args)
        if learned_entry is not None:
            action = "allow"
            reason = tool_risk.auto_approve_reason(learned_entry)
    value = money(value_usd)
    decision = {"allow": "allow", "deny": "deny"}.get(action, "pending")
    call_id = store.insert_tool_call(ToolCallRow(agent_id, tool_name, args or {}, decision,
                                                 args if decision == "allow" else {},
                                                 "policy" if decision != "pending" else "", reason, value))
    if decision == "deny":
        store.insert_action(ActionRow(agent_id, "TOOL_DENY", "policy", f"{tool_name}: {reason}", value))
    if learned_entry is not None and decision == "allow":
        # The audit trail: an operator must be able to see which calls went through on
        # their own, and on what evidence.
        store.insert_action(ActionRow(agent_id, "TOOL_AUTO_ALLOW", "brain:toolrisk",
                                      f"{tool_name}: {reason}", value))
    return store.get_tool_call(call_id)


def decide_tool_call(store, call_id: int, decision: str, final_args: Optional[dict], decided_by: str,
                     reason: str) -> dict:
    decision = (decision or "").strip().lower()
    if decision not in ("allow", "deny", "rewrite"):
        raise ApiError(400, "decision must be allow, deny or rewrite")
    if decided_by not in DECIDERS:
        raise ApiError(400, f"decided_by must be one of {', '.join(DECIDERS)}")
    if decision == "rewrite" and not isinstance(final_args, dict):
        raise ApiError(400, "rewrite needs final_args (the new arguments)")
    call = store.get_tool_call(call_id)
    if call is None:
        raise ApiError(404, f"tool call {call_id} not found")
    if call["decision"] != "pending":
        raise ApiError(409, f"tool call {call_id} already decided: {call['decision']}")
    final = (final_args if decision == "rewrite" else call["args"] if decision == "allow" else {}) or {}
    store.decide_tool_call(call_id, decision, final, decided_by, reason)
    saved = saved_by_tool_decision(decision, call["args"], final, float(call.get("value_usd") or 0))
    store.insert_action(ActionRow(call["agent_id"], f"TOOL_{decision.upper()}", actor_for(decided_by),
                                  f"{call['tool_name']}: {reason or decision}", saved))
    return store.get_tool_call(call_id)


# ── views ──
def _latest_by_agent(rows: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for r in rows:  # rows are oldest → newest
        latest[r["agent_id"]] = r
    return latest


def fleet_view(store) -> list[dict]:
    metrics = _latest_by_agent(store.recent_metrics(minutes=1))
    verdicts: dict[str, dict] = {}
    for v in store.recent_verdicts(limit=50):  # newest first
        verdicts.setdefault(v["agent_id"], v)
    return [agent_view(a, metrics.get(a["agent_id"]), verdicts.get(a["agent_id"])) for a in store.list_agents()]


def graph(store, minutes: float, loop_threshold: float) -> dict:
    """Nodes = agents, tools, models. Edges carry call counts; in_cycle marks looping agents' edges."""
    spans = store.recent_spans(minutes=minutes)
    metrics = _latest_by_agent(store.recent_metrics(minutes=1))
    edges: dict[tuple[str, str], int] = defaultdict(int)
    nodes: dict[str, dict] = {}
    for s in spans:
        agent = s["agent_id"]
        nodes.setdefault(agent, {"id": agent, "kind": "agent", "label": agent})
        if s["operation"] == "chat" and s.get("model"):
            target = f"model:{s['model']}"
            nodes.setdefault(target, {"id": target, "kind": "model", "label": s["model"]})
        elif s["operation"] == "execute_tool" and s.get("tool_name"):
            target = f"tool:{s['tool_name']}"
            nodes.setdefault(target, {"id": target, "kind": "tool", "label": s["tool_name"]})
        else:
            continue
        edges[(agent, target)] += 1
    looping = {a for a, m in metrics.items()
               if float(m.get("loop_score") or 0) >= loop_threshold or m.get("tool_cycle")}
    return {"nodes": list(nodes.values()),
            "edges": [{"source": a, "target": t, "count": n, "in_cycle": a in looping} for (a, t), n in edges.items()]}


def node_feed(store, agent_id: str, minutes: float, limit: int) -> dict:
    """LangGraph/CrewAI node events for one agent (CONTRACTS §6 /nodes): what ran, what it changed, where it went.
    edges count transitions between consecutive nodes of the same run, so the dashboard can draw the live graph."""
    spans = [s for s in store.recent_spans(minutes=minutes, agent_id=agent_id) if s.get("operation") == "graph_node"]
    spans.sort(key=lambda s: (float(s.get("start_ts") or 0), int(s.get("id") or 0)))
    items = []
    for s in spans:
        d = load_json(s.get("detail"))
        items.append({"ts": s.get("start_ts"), "node": d.get("node") or str(s.get("name", "")).split(" ", 1)[-1],
                      "step": d.get("step"), "framework": d.get("framework", ""), "changed": d.get("changed") or {},
                      "next": d.get("next", ""), "status": s.get("status", "ok"), "duration_ms": s.get("duration_ms"),
                      "trace_id": s.get("trace_id", "")})
    edges: dict[tuple[str, str], int] = defaultdict(int)
    for prev, cur in zip(items, items[1:]):
        if prev["trace_id"] == cur["trace_id"]:
            edges[(prev["node"], cur["node"])] += 1
    last = items[-1] if items else None
    return {"items": items[-limit:],
            "edges": [{"source": a, "target": b, "count": n} for (a, b), n in sorted(edges.items())],
            "last_node": last["node"] if last else None, "next_node": (last["next"] or None) if last else None}


def roi(store, horizon_minutes: float) -> dict:
    from eval.roi import build_report

    return build_report(store.recent_spans(minutes=24 * 60), store.recent_actions(limit=1000),
                        store.list_tool_calls(limit=1000), horizon_minutes)


def dumps(obj) -> str:
    return json.dumps(obj, default=str)


# ── auto-heal proposals (CONTRACTS §7) ──
def list_heal_proposals(store, status: Optional[str], agent_id: Optional[str], limit: int) -> list[dict]:
    return store.list_heal_proposals(status=status, agent_id=agent_id, limit=limit)


def decide_heal_proposal(store, proposal_id: int, decision: str, requested_by: str, reason: str) -> dict:
    """
    Apply or reject a heal proposal.

    The human path runs the SAME code as the auto path (brain/heal.py): the patch is written to
    the agent's memory, the proposal becomes `applied` and an AUTO_HEAL action is recorded. A
    proposal whose base version is stale becomes `expired` — the newer memory wins.
    """
    from brain.heal import PatchRejected, decide as decide_heal

    if requested_by not in ("human", "mcp"):
        raise ApiError(400, "requested_by must be one of human, mcp")
    actor = "mcp" if requested_by == "mcp" else "human"
    try:
        return decide_heal(store, proposal_id, decision, actor, reason)
    except LookupError as exc:
        raise ApiError(404, str(exc))
    except ValueError as exc:
        raise ApiError(409, str(exc))
    except PatchRejected as exc:
        raise ApiError(400, str(exc))


__all__ = ["ApiError", "post_command", "save_memory", "request_tool_call", "decide_tool_call",
           "fleet_view", "graph", "node_feed", "roi", "load_json", "dumps",
           "list_heal_proposals", "decide_heal_proposal"]
