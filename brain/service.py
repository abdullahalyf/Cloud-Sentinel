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
from shared.contracts import (COMMAND_TYPES, ROGUE_KINDS, ActionRow, CommandRow, ToolCallRow, agent_view,
                              load_json)


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


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
                base_version: Optional[int]) -> dict:
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
    try:
        row = store.write_memory(agent_id, content, edited_by, reason, base_version)
    except MemoryConflict as exc:
        raise ApiError(409, str(exc))
    if edited_by in ("human", "mcp"):
        store.insert_action(ActionRow(agent_id, "MEMORY_EDIT", edited_by, reason or "memory edited"))
    return row


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
                      value_usd: Optional[float]) -> dict:
    """Called by the SDK before running a tool. Policy decides now, or leaves it pending for a human."""
    agent_id = check_agent_id(agent_id)
    tool_name = (tool_name or "").strip()
    if not tool_name:
        raise ApiError(400, "tool_name is required")
    args = args if isinstance(args, dict) else {}
    try:
        action, reason = policy.decide_tool(tool_name, args)
    except Exception as exc:  # a broken rule must fail SAFE: a human decides
        action, reason = "approval", f"policy error ({exc}); needs a human"
    agent = store.get_agent(agent_id)
    if agent and agent.get("state") in ("paused", "killed"):
        # second layer: even if the container could not be frozen, a tripped agent gets no tools
        action, reason = "deny", f"agent is {agent['state']} by CloudSentinel"
    value = money(value_usd)
    decision = {"allow": "allow", "deny": "deny"}.get(action, "pending")
    call_id = store.insert_tool_call(ToolCallRow(agent_id, tool_name, args or {}, decision,
                                                 args if decision == "allow" else {},
                                                 "policy" if decision != "pending" else "", reason, value))
    if decision == "deny":
        store.insert_action(ActionRow(agent_id, "TOOL_DENY", "policy", f"{tool_name}: {reason}", value))
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


def roi(store, horizon_minutes: float) -> dict:
    from eval.roi import build_report

    return build_report(store.recent_spans(minutes=24 * 60), store.recent_actions(limit=1000),
                        store.list_tool_calls(limit=1000), horizon_minutes)


def dumps(obj) -> str:
    return json.dumps(obj, default=str)


__all__ = ["ApiError", "post_command", "save_memory", "request_tool_call", "decide_tool_call",
           "fleet_view", "graph", "roi", "load_json", "dumps"]
