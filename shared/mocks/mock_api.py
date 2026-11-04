"""
Mock C2 API (CONTRACTS §6) with moving fake data. No brain, no database, no Docker needed.

    python -m shared.mocks.mock_api      → http://localhost:8000  (docs at /docs)

Used by: dashboard (Tamjid) and MCP development. Shapes come from shared.contracts, and
shared/tests/test_api_parity.py checks they match the real API.
States cycle every ~60 s so every UI state can be seen: beta loops → paused, gamma → killed,
delta has a pending refund approval.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException

from shared.contracts import (CONTRACT_VERSION, ROI_FORMULA, ActionRow, AlertRow, MetricRow, ToolCallRow,
                              VerdictRow, agent_view, utc_now_iso)

AGENTS = ["alpha", "beta", "gamma", "delta"]
BUDGETS = {"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2}
T0 = time.time()


def _phase() -> float:
    return (time.time() - T0) % 60


def _state(agent: str) -> str:
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


MEMORY: dict[str, dict] = {"beta": {"id": 1, "agent_id": "beta", "version": 1, "edited_by": "agent", "reason": "",
                                    "content": {"order_4471": "orders API returned 500 - retry until success"},
                                    "created_at": utc_now_iso()}}
TOOL_CALLS: dict[int, dict] = {1: ToolCallRow("delta", "issue_refund", {"order_id": 4471, "amount": 50000},
                                              "pending", {}, "", "refunds over 5,000 BDT need a human", 410.0)
                               .to_row() | {"id": 1, "args": {"order_id": 4471, "amount": 50000}, "final_args": {}}}
COMMANDS: list[dict] = []
ACTIONS: list[dict] = [ActionRow("beta", "PAUSE", "claude", "semantic loop on order 4471", 2.52, 210000).to_row() | {"id": 2},
                       ActionRow("gamma", "KILL", "rules", "Hard limit: 80,816 tokens/min", 129.6, 4800000).to_row() | {"id": 1}]
ALERTS: list[dict] = [AlertRow("beta", "warning", "loop_semantic,injection", "semantic loop score 0.85").to_row() | {"id": 1}]


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
            "memory": MEMORY.get(agent_id)}


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


@app.post("/v1/agents/{agent_id}/commands")
def command(agent_id: str, body: dict[str, Any]) -> dict:
    COMMANDS.append({"id": len(COMMANDS) + 1, "agent_id": agent_id, **body})
    ACTIONS.insert(0, ActionRow(agent_id, body.get("command", "?"), "human", body.get("reason", "")).to_row()
                   | {"id": len(ACTIONS) + 1})
    return {"id": len(COMMANDS), "status": "pending"}


@app.get("/v1/agents/{agent_id}/memory")
def get_memory(agent_id: str) -> dict:
    if agent_id not in MEMORY:
        raise HTTPException(404, f"no memory for {agent_id}")
    return MEMORY[agent_id]


@app.put("/v1/agents/{agent_id}/memory")
def put_memory(agent_id: str, body: dict[str, Any]) -> dict:
    old = MEMORY.get(agent_id, {"version": 0})
    if body.get("base_version") is not None and body.get("edited_by") == "agent" and old["version"] > body["base_version"]:
        raise HTTPException(409, "memory changed by a human; reload it first")
    MEMORY[agent_id] = {"id": old["version"] + 1, "agent_id": agent_id, "version": old["version"] + 1,
                        "content": body.get("content", {}), "edited_by": body.get("edited_by", "human"),
                        "reason": body.get("reason", ""), "created_at": utc_now_iso()}
    return MEMORY[agent_id]


@app.get("/v1/agents/{agent_id}/memory/history")
def memory_history(agent_id: str, limit: int = 10) -> dict:
    return {"items": [MEMORY[agent_id]] if agent_id in MEMORY else []}


@app.post("/v1/agents/{agent_id}/tool-calls")
def tool_call(agent_id: str, body: dict[str, Any]) -> dict:
    cid = max(TOOL_CALLS) + 1
    TOOL_CALLS[cid] = ToolCallRow(agent_id, body["tool_name"], body.get("args", {}), "allow", body.get("args", {}),
                                  "policy", "mock allows everything", body.get("value_usd") or 0).to_row() | {
        "id": cid, "args": body.get("args", {}), "final_args": body.get("args", {})}
    return TOOL_CALLS[cid]


@app.get("/v1/tool-calls")
def tool_calls(status: Optional[str] = None, limit: int = 50) -> dict:
    return {"items": [c for c in TOOL_CALLS.values() if status is None or c["decision"] == status][:limit]}


@app.get("/v1/tool-calls/{call_id}")
def get_tool_call(call_id: int) -> dict:
    if call_id not in TOOL_CALLS:
        raise HTTPException(404, "not found")
    return TOOL_CALLS[call_id]


@app.post("/v1/tool-calls/{call_id}/decision")
def decide(call_id: int, body: dict[str, Any]) -> dict:
    call = TOOL_CALLS.get(call_id)
    if call is None:
        raise HTTPException(404, "not found")
    if call["decision"] != "pending":
        raise HTTPException(409, "already decided")
    call.update(decision=body["decision"], final_args=body.get("final_args") or call["args"],
                decided_by=body.get("decided_by", "human"), reason=body.get("reason", ""), decided_at=utc_now_iso())
    return call


@app.get("/v1/roi")
def roi() -> dict:
    saved = [{"action_id": a["id"], "agent_id": a["agent_id"], "action": a["action"], "actor": a["actor"],
              "usd": a["usd_saved_estimate"]} for a in ACTIONS if a["usd_saved_estimate"]]
    return {"total_spend_usd": round((time.time() - T0) * 0.002, 4), "spend_by_agent": {a: 0.01 for a in AGENTS},
            "saved_usd": round(sum(s["usd"] for s in saved), 4), "saved_by_action": saved,
            "interventions": len(saved), "tool_calls_held": 1, "tasks_succeeded": 42,
            "cost_per_successful_task_usd": 0.0021, "horizon_minutes": 60.0, "formula": ROI_FORMULA}


if __name__ == "__main__":
    import uvicorn

    print("MOCK CloudSentinel API on http://localhost:8000  (docs: /docs)")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
