"""
Mock C2 API (CONTRACTS §6) with moving fake data. No brain, no database, no Docker needed.

    python -m shared.mocks.mock_api      → http://localhost:8000  (docs at /docs)

Used by: dashboard (Tamjid) and MCP development. Shapes come from shared.contracts, and
shared/tests/test_api_parity.py checks they match the real API.
States cycle every ~60 s so every UI state can be seen: beta loops → paused, gamma → killed,
delta has a pending refund approval.

It behaves like the real API where a client could notice: the same 400/404/409 errors, commands
change the agent's state for OVERRIDE_SECONDS (so a Pause button visibly works), tool calls follow
brain/policies.yaml (a 50,000 refund is held as `pending`), memory keeps every version, and
WS /v1/stream pushes events.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from shared.contracts import (COMMAND_TYPES, CONTRACT_VERSION, ROGUE_KINDS, ROI_FORMULA, TOOL_DECISIONS, ActionRow,
                              AlertRow, MetricRow, ToolCallRow, VerdictRow, agent_view, utc_now_iso)

AGENTS = ["alpha", "beta", "gamma", "delta"]
BUDGETS = {"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2}
T0 = time.time()
OVERRIDE_SECONDS = 20.0
OVERRIDES: dict[str, tuple[str, float]] = {}   # agent → (state, until) set by commands
COMMAND_STATE = {"PAUSE": "paused", "KILL": "killed", "RESUME": "probation", "RESTART": "probation"}


def _phase() -> float:
    return (time.time() - T0) % 60


def _state(agent: str) -> str:
    forced = OVERRIDES.get(agent)
    if forced and time.time() < forced[1]:
        return forced[0]
    p = _phase()
    if agent == "beta":
        return "healthy" if p < 15 else "suspicious" if p < 22 else "paused" if p < 40 else "probation" if p < 50 else "healthy"
    if agent == "gamma":
        return "healthy" if p < 30 else "killed"
    return "healthy"


def _metric(agent: str, t: float) -> dict:
    st = _state(agent)
    base = {"alpha": 4000, "beta": 3500, "gamma": 5000, "delta": 2500}[agent]
    wave = 1 + 0.2 * math.sin(t / 7 + AGENTS.index(agent))
    tpm = 0 if st in ("paused", "killed") else int(base * wave * (5 if st == "suspicious" else 1))
    if agent == "gamma" and 25 < _phase() < 30:
        tpm = 80_000
    loop = 0.85 if (agent == "beta" and st in ("suspicious", "paused")) else round(random.uniform(0, 0.1), 2)
    return MetricRow(agent, st, tpm, round(tpm * 4e-6, 5), round(tpm / 20000, 2), int(t - T0) * 50,
                     round((t - T0) * 0.0005, 4), BUDGETS[agent], 1 if loop < 0.5 else 2, loop,
                     int(loop > 0.5), 90.0, 17.6).to_row()


def _verdict() -> dict:
    return VerdictRow("beta", "claude", "PAUSE", 0.93, "semantic_loop",
                      "Same intent 'order 4471 status' repeated 14x in 60s with failing tool calls; log text "
                      "addressed to the monitor treated as a red flag.",
                      'Set memory "order_4471" to "cancelled - skip it and move on" so the agent stops retrying.',
                      812.0).to_row() | {"id": 1}


MEMORY: dict[str, list[dict]] = {}
TOOL_CALLS: dict[int, dict] = {}
COMMANDS: list[dict] = []
ACTIONS: list[dict] = []
ALERTS: list[dict] = []


def seed() -> None:
    """(Re)fill the fake data in place. Called at import and by POST /v1/mock/reset (and tests)."""
    for coll in (MEMORY, TOOL_CALLS, COMMANDS, ACTIONS, ALERTS, OVERRIDES):
        coll.clear()
    BUDGETS.update({"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2})
    MEMORY["beta"] = [{"id": 1, "agent_id": "beta", "version": 1, "edited_by": "agent", "reason": "",
                       "created_at": utc_now_iso(),
                       "content": {"order_4471": "orders API returned 500 - retry until success"}}]
    TOOL_CALLS[1] = ToolCallRow("delta", "issue_refund", {"order_id": 4471, "amount": 50000}, "pending", {}, "",
                                "refunds over 5,000 BDT need a human", 410.0).to_row() | {
        "id": 1, "args": {"order_id": 4471, "amount": 50000}, "final_args": {}}
    ACTIONS.extend([
        ActionRow("beta", "PAUSE", "claude", "semantic loop on order 4471", 2.52, 210000).to_row() | {"id": 2},
        ActionRow("gamma", "KILL", "rules", "Hard limit: 80,816 tokens/min", 129.6, 4800000).to_row() | {"id": 1}])
    ALERTS.append(AlertRow("beta", "warning", "loop_semantic,injection", "semantic loop score 0.85").to_row() | {"id": 1})


seed()


def _fleet() -> list[dict]:
    now = time.time()
    out = []
    for a in AGENTS:
        m = _metric(a, now)
        row = {"agent_id": a, "display_name": a, "runtime": "mock", "state": _state(a), "budget_usd": BUDGETS[a],
               "spend_usd": m["spend_usd"], "total_tokens": m["total_tokens"], "updated_at": utc_now_iso()}
        out.append(agent_view(row, m, _verdict() if a == "beta" and _state(a) != "healthy" else None))
    return out


app = FastAPI(title="CloudSentinel MOCK C2 API", version=f"contract-{CONTRACT_VERSION}")


@app.get("/v1/health")
def health() -> dict:
    return {"ok": True, "mode": "mock", "judge": "claude", "contract": CONTRACT_VERSION}


@app.get("/v1/fleet")
def fleet() -> dict:
    return {"agents": _fleet()}


@app.get("/v1/agents/{agent_id}")
def agent(agent_id: str) -> dict:
    view = next((a for a in _fleet() if a["agent_id"] == agent_id), None)
    if view is None:
        raise HTTPException(404, f"agent {agent_id} not found")
    return {"agent": view, "spans": [], "verdicts": [_verdict()] if agent_id == "beta" else [],
            "memory": _latest_memory(agent_id)}


HEALTHY_PATH = ["classify", "lookup_order", "decide", "refund"]


def _node_events(agent: str, now: float, seconds: int = 60) -> list[dict]:
    """Fake LangGraph node events, one per second: delta runs the refund graph, beta loops while rogue."""
    if agent not in ("beta", "delta"):
        return []
    items = []
    for i in range(seconds, 0, -1):
        t = int(now) - i
        looping = agent == "beta" and _state("beta") in ("suspicious", "paused") and i < 25
        if looping:
            node = ["lookup_order", "retry"][t % 2]
            nxt = "retry" if node == "lookup_order" else "lookup_order"
            changed = {"status": "error: orders API returned 500", "attempts": str(t % 97)} if node == "lookup_order" \
                else {"answer": f"retrying ({t % 97})"}
            run, status = "loop-4471", "error" if node == "lookup_order" else "ok"
        else:
            k = t % len(HEALTHY_PATH)
            node, nxt = HEALTHY_PATH[k], (HEALTHY_PATH + ["__end__"])[k + 1]
            changed = {"classify": {"intent": "refund"}, "lookup_order": {"status": "shipped"},
                       "decide": {"amount": "800"}, "refund": {"answer": "refunded 800 BDT"}}[node]
            run, status = f"run-{t // len(HEALTHY_PATH)}", "ok"
        items.append({"ts": float(t), "node": node, "step": t % 100, "framework": "langgraph", "changed": changed,
                      "next": nxt, "status": status, "duration_ms": 120.0, "trace_id": run})
    return items


@app.get("/v1/agents/{agent_id}/nodes")
def nodes(agent_id: str, minutes: float = 10, limit: int = 100) -> dict:
    items = _node_events(agent_id, time.time())
    edges: dict[tuple[str, str], int] = {}
    for prev, cur in zip(items, items[1:]):
        if prev["trace_id"] == cur["trace_id"]:
            edges[(prev["node"], cur["node"])] = edges.get((prev["node"], cur["node"]), 0) + 1
    last = items[-1] if items else None
    return {"items": items[-max(1, limit):],
            "edges": [{"source": a, "target": b, "count": n} for (a, b), n in sorted(edges.items())],
            "last_node": last["node"] if last else None, "next_node": last["next"] if last else None}


@app.get("/v1/metrics")
def metrics(minutes: float = 5, agent_id: Optional[str] = None) -> dict:
    now, rows = time.time(), []
    for i in range(int(min(minutes, 5) * 60), 0, -2):
        for a in AGENTS if agent_id is None else [agent_id]:
            rows.append(_metric(a, now - i) | {"id": len(rows) + 1, "created_at": utc_now_iso()})
    return {"metrics": rows}


@app.get("/v1/graph")
def graph(minutes: float = 2) -> dict:
    nodes = [{"id": a, "kind": "agent", "label": a} for a in AGENTS] + [
        {"id": "model:sim", "kind": "model", "label": "sim"},
        {"id": "tool:orders_api", "kind": "tool", "label": "orders_api"},
        {"id": "tool:issue_refund", "kind": "tool", "label": "issue_refund"}]
    looping = _state("beta") in ("suspicious", "paused")
    edges = [{"source": a, "target": "model:sim", "count": 20, "in_cycle": a == "beta" and looping} for a in AGENTS]
    edges += [{"source": "beta", "target": "tool:orders_api", "count": 40 if looping else 5, "in_cycle": looping},
              {"source": "delta", "target": "tool:issue_refund", "count": 1, "in_cycle": False}]
    return {"nodes": nodes, "edges": edges}


@app.get("/v1/verdicts")
def verdicts(limit: int = 20) -> dict:
    return {"items": [_verdict()]}


@app.get("/v1/actions")
def actions(limit: int = 50) -> dict:
    return {"items": ACTIONS[:limit]}


@app.get("/v1/alerts")
def alerts(limit: int = 50) -> dict:
    return {"items": ALERTS[:limit]}


def _bad(status: int, detail: str):
    raise HTTPException(status, detail)


def _action(agent_id: str, action: str, actor: str, reason: str, usd: float = 0.0) -> None:
    ACTIONS.insert(0, ActionRow(agent_id, action, actor, reason, usd).to_row() | {"id": len(ACTIONS) + 1})


@app.post("/v1/agents/{agent_id}/commands")
def command(agent_id: str, body: dict[str, Any]) -> dict:
    cmd = str(body.get("command", "")).upper()
    params = body.get("params") or {}
    if cmd not in COMMAND_TYPES:
        _bad(400, f"unknown command {cmd}; use one of {', '.join(COMMAND_TYPES)}")
    if cmd == "SET_BUDGET":
        try:
            if float(params.get("budget_usd", -1)) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            _bad(400, "SET_BUDGET needs params.budget_usd > 0")
        BUDGETS[agent_id] = float(params["budget_usd"])
    if cmd == "GO_ROGUE" and params.get("kind", "paraphrase_loop") not in ROGUE_KINDS:
        _bad(400, f"kind must be one of {ROGUE_KINDS}")
    COMMANDS.append({"id": len(COMMANDS) + 1, "agent_id": agent_id, **body})
    if cmd in COMMAND_STATE and agent_id in AGENTS:
        OVERRIDES[agent_id] = (COMMAND_STATE[cmd], time.time() + OVERRIDE_SECONDS)
    actor = "mcp" if body.get("requested_by") == "mcp" else "human"
    _action(agent_id, cmd, actor, body.get("reason") or f"{cmd.lower()} (mock)", 2.52 if cmd in ("PAUSE", "KILL") else 0)
    return {"id": len(COMMANDS), "status": "pending"}


def _latest_memory(agent_id: str) -> Optional[dict]:
    versions = MEMORY.get(agent_id)
    return versions[-1] if versions else None


@app.get("/v1/agents/{agent_id}/memory")
def get_memory(agent_id: str) -> dict:
    mem = _latest_memory(agent_id)
    if mem is None:
        _bad(404, f"no memory for {agent_id}")
    return mem


@app.put("/v1/agents/{agent_id}/memory")
def put_memory(agent_id: str, body: dict[str, Any]) -> dict:
    content, edited_by, base = body.get("content"), body.get("edited_by", "human"), body.get("base_version")
    if not isinstance(content, dict):
        _bad(400, "memory content must be a JSON object")
    if edited_by not in ("agent", "human", "mcp"):
        _bad(400, "edited_by must be one of agent, human, mcp")
    versions = MEMORY.setdefault(agent_id, [])
    last = versions[-1]["version"] if versions else 0
    newer_by_others = [v for v in versions if base is not None and v["version"] > base and v["edited_by"] != "agent"]
    if edited_by == "agent" and newer_by_others:
        _bad(409, "memory changed by a human; reload it first")
    row = {"id": sum(len(v) for v in MEMORY.values()) + 1, "agent_id": agent_id, "version": last + 1,
           "content": content, "edited_by": edited_by, "reason": body.get("reason", ""), "created_at": utc_now_iso()}
    versions.append(row)
    if edited_by in ("human", "mcp"):
        _action(agent_id, "MEMORY_EDIT", edited_by, body.get("reason") or "memory edited")
    return row


@app.get("/v1/agents/{agent_id}/memory/history")
def memory_history(agent_id: str, limit: int = 10) -> dict:
    return {"items": list(reversed(MEMORY.get(agent_id, [])))[:max(1, limit)]}


def _policy(tool_name: str, args: dict) -> tuple[str, str]:
    """Same decision as the real brain (brain/policies.yaml); allow-all if the brain isn't importable."""
    try:
        from brain.policy import Policy

        return Policy.load("brain/policies.yaml").decide_tool(tool_name, args)
    except Exception:
        return "allow", "mock allows everything"


@app.post("/v1/agents/{agent_id}/tool-calls")
def tool_call(agent_id: str, body: dict[str, Any]) -> dict:
    name, args = str(body.get("tool_name") or "").strip(), body.get("args") or {}
    if not name:
        _bad(400, "tool_name is required")
    action, reason = _policy(name, args)
    if _state(agent_id) in ("paused", "killed"):
        action, reason = "deny", f"agent is {_state(agent_id)} by CloudSentinel"
    decision = {"allow": "allow", "deny": "deny"}.get(action, "pending")
    cid = max(TOOL_CALLS) + 1
    TOOL_CALLS[cid] = ToolCallRow(agent_id, name, args, decision, args if decision == "allow" else {},
                                  "policy" if decision != "pending" else "", reason,
                                  float(body.get("value_usd") or 0)).to_row() | {
        "id": cid, "args": args, "final_args": args if decision == "allow" else {}}
    return TOOL_CALLS[cid]


@app.get("/v1/tool-calls")
def tool_calls(status: Optional[str] = None, limit: int = 50) -> dict:
    if status is not None and status not in TOOL_DECISIONS:
        _bad(400, f"status must be one of {', '.join(TOOL_DECISIONS)}")
    rows = sorted(TOOL_CALLS.values(), key=lambda c: -c["id"])
    return {"items": [c for c in rows if status is None or c["decision"] == status][:max(1, limit)]}


@app.get("/v1/tool-calls/{call_id}")
def get_tool_call(call_id: int) -> dict:
    if call_id not in TOOL_CALLS:
        _bad(404, f"tool call {call_id} not found")
    return TOOL_CALLS[call_id]


@app.post("/v1/tool-calls/{call_id}/decision")
def decide(call_id: int, body: dict[str, Any]) -> dict:
    decision, final_args = str(body.get("decision", "")).lower(), body.get("final_args")
    if decision not in ("allow", "deny", "rewrite"):
        _bad(400, "decision must be allow, deny or rewrite")
    if body.get("decided_by", "human") not in ("human", "mcp"):
        _bad(400, "decided_by must be one of human, mcp")
    if decision == "rewrite" and not isinstance(final_args, dict):
        _bad(400, "rewrite needs final_args (the new arguments)")
    call = TOOL_CALLS.get(call_id)
    if call is None:
        _bad(404, f"tool call {call_id} not found")
    if call["decision"] != "pending":
        _bad(409, f"tool call {call_id} already decided: {call['decision']}")
    final = final_args if decision == "rewrite" else call["args"] if decision == "allow" else {}
    call.update(decision=decision, final_args=final, decided_by=body.get("decided_by", "human"),
                reason=body.get("reason", ""), decided_at=utc_now_iso())
    _action(call["agent_id"], f"TOOL_{decision.upper()}", call["decided_by"], f"{call['tool_name']}: {decision}",
            call["value_usd"] if decision == "deny" else 0)
    return call


@app.post("/v1/mock/reset")
def mock_reset() -> dict:
    """Mock only (not in the contract): back to the seeded data (pending refund, beta's bad memory)."""
    seed()
    return {"ok": True}


@app.websocket("/v1/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    seen = {"action": 0, "verdict": 0, "alert": 0, "tool_call": 0}
    try:
        while True:
            sources = {"action": ACTIONS, "verdict": [_verdict()], "alert": ALERTS, "tool_call": list(TOOL_CALLS.values())}
            for kind, rows in sources.items():
                for row in sorted(rows, key=lambda r: r["id"]):
                    if row["id"] > seen[kind]:
                        seen[kind] = row["id"]
                        await ws.send_json({"type": kind, "data": row})
            await ws.send_json({"type": "metric", "data": _fleet()})
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.get("/v1/roi")
def roi() -> dict:
    saved = [{"action_id": a["id"], "agent_id": a["agent_id"], "action": a["action"], "actor": a["actor"],
              "usd": a["usd_saved_estimate"]} for a in ACTIONS if a["usd_saved_estimate"]]
    return {"total_spend_usd": round((time.time() - T0) * 0.002, 4), "spend_by_agent": {a: 0.01 for a in AGENTS},
            "saved_usd": round(sum(s["usd"] for s in saved), 4), "saved_by_action": saved,
            "interventions": len(saved), "tool_calls_held": 1, "tasks_total": 51, "tasks_succeeded": 42,
            "cost_per_successful_task_usd": 0.0021, "wasted_usd": 0.0109, "tasks_by_agent": {
                a: {"tasks": n, "succeeded": ok, "failed": n - ok, "abandoned": 0, "success_rate": round(ok / n, 3),
                    "spend_usd": spend, "wasted_usd": round(spend * (n - ok) / n, 4), "unattributed_usd": 0.0,
                    "cost_per_success_usd": round(spend / ok, 4) if ok else 0.0}
                for a, n, ok, spend in [("alpha", 12, 12, 0.0216), ("beta", 14, 6, 0.0198), ("gamma", 12, 12, 0.0222),
                                        ("delta", 13, 12, 0.0251)]},
            "horizon_minutes": 60.0, "formula": ROI_FORMULA}


if __name__ == "__main__":
    import uvicorn

    print("MOCK CloudSentinel API on http://localhost:8000  (docs: /docs)")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
