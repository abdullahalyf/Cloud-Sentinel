"""
C2 (Command & Control) REST + WebSocket API (CONTRACTS §6). Interactive docs: http://localhost:8000/docs

Thin layer: validation + brain.service. The engine executes commands on its next tick.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from brain import service
from brain.policy import Policy
from shared.config import Settings
from shared.contracts import CONTRACT_VERSION, TOOL_DECISIONS

log = logging.getLogger("brain.api")


class CommandIn(BaseModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "dashboard"
    reason: str = ""


class MemoryIn(BaseModel):
    content: dict[str, Any]
    edited_by: str = "human"
    reason: str = ""
    base_version: Optional[int] = None


class ToolCallIn(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    value_usd: Optional[float] = None


class DecisionIn(BaseModel):
    decision: str
    final_args: Optional[dict[str, Any]] = None
    decided_by: str = "human"
    reason: str = ""


def clamp_limit(limit: int, top: int = 1000) -> int:
    return max(1, min(int(limit), top))


def clamp_minutes(minutes: float, top: float = 24 * 60) -> float:
    return max(0.1, min(float(minutes), top)) if minutes == minutes else 5.0  # NaN → default


def create_app(store, policy: Policy, cfg: Settings, mode: str, judge: str) -> FastAPI:
    app = FastAPI(title="CloudSentinel C2 API", version=f"contract-{CONTRACT_VERSION}",
                  description="Command & Control for AI agent fleets: observe, pause, heal, kill.")

    def auth(x_cs_token: str = Header(default="")) -> None:
        if cfg.api_token and x_cs_token != cfg.api_token:
            raise HTTPException(401, "missing or wrong X-CS-Token")

    def call(fn, *args):
        try:
            return fn(*args)
        except service.ApiError as exc:
            raise HTTPException(exc.status, exc.detail)

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True, "mode": mode, "judge": judge, "contract": CONTRACT_VERSION}

    @app.get("/v1/fleet", dependencies=[Depends(auth)])
    def fleet() -> dict:
        return {"agents": service.fleet_view(store)}

    @app.get("/v1/agents/{agent_id}", dependencies=[Depends(auth)])
    def agent(agent_id: str) -> dict:
        view = next((a for a in service.fleet_view(store) if a["agent_id"] == agent_id), None)
        if view is None:
            raise HTTPException(404, f"agent {agent_id} not found")
        return {"agent": view, "spans": store.recent_spans(minutes=10, agent_id=agent_id)[-50:],
                "verdicts": store.recent_verdicts(limit=10, agent_id=agent_id), "memory": store.get_memory(agent_id)}

    @app.get("/v1/metrics", dependencies=[Depends(auth)])
    def metrics(minutes: float = 5, agent_id: Optional[str] = None) -> dict:
        return {"metrics": store.recent_metrics(minutes=clamp_minutes(minutes), agent_id=agent_id)}

    @app.get("/v1/graph", dependencies=[Depends(auth)])
    def graph(minutes: float = 2) -> dict:
        return service.graph(store, clamp_minutes(minutes), cfg.loop_score_threshold)

    @app.get("/v1/verdicts", dependencies=[Depends(auth)])
    def verdicts(limit: int = 20) -> dict:
        return {"items": store.recent_verdicts(limit=clamp_limit(limit))}

    @app.get("/v1/actions", dependencies=[Depends(auth)])
    def actions(limit: int = 50) -> dict:
        return {"items": store.recent_actions(limit=clamp_limit(limit))}

    @app.get("/v1/alerts", dependencies=[Depends(auth)])
    def alerts(limit: int = 50) -> dict:
        return {"items": store.recent_alerts(limit=clamp_limit(limit))}

    @app.post("/v1/agents/{agent_id}/commands", dependencies=[Depends(auth)])
    def command(agent_id: str, body: CommandIn) -> dict:
        cid = call(service.post_command, store, agent_id, body.command, body.params, body.requested_by, body.reason)
        return {"id": cid, "status": "pending"}

    @app.get("/v1/agents/{agent_id}/memory", dependencies=[Depends(auth)])
    def get_memory(agent_id: str) -> dict:
        mem = store.get_memory(agent_id)
        if mem is None:
            raise HTTPException(404, f"no memory for {agent_id}")
        return mem

    @app.put("/v1/agents/{agent_id}/memory", dependencies=[Depends(auth)])
    def put_memory(agent_id: str, body: MemoryIn) -> dict:
        return call(service.save_memory, store, agent_id, body.content, body.edited_by, body.reason, body.base_version)

    @app.get("/v1/agents/{agent_id}/memory/history", dependencies=[Depends(auth)])
    def memory_history(agent_id: str, limit: int = 10) -> dict:
        return {"items": store.memory_history(agent_id, limit=clamp_limit(limit, 100))}

    @app.post("/v1/agents/{agent_id}/tool-calls", dependencies=[Depends(auth)])
    def tool_call(agent_id: str, body: ToolCallIn) -> dict:
        return call(service.request_tool_call, store, policy, agent_id, body.tool_name, body.args, body.value_usd)

    @app.get("/v1/tool-calls", dependencies=[Depends(auth)])
    def tool_calls(status: Optional[str] = None, limit: int = 50) -> dict:
        if status is not None and status not in TOOL_DECISIONS:
            raise HTTPException(400, f"status must be one of {', '.join(TOOL_DECISIONS)}")
        return {"items": store.list_tool_calls(status=status, limit=clamp_limit(limit))}

    @app.get("/v1/tool-calls/{call_id}", dependencies=[Depends(auth)])
    def get_tool_call(call_id: int) -> dict:
        row = store.get_tool_call(call_id)
        if row is None:
            raise HTTPException(404, f"tool call {call_id} not found")
        return row

    @app.post("/v1/tool-calls/{call_id}/decision", dependencies=[Depends(auth)])
    def decide(call_id: int, body: DecisionIn) -> dict:
        return call(service.decide_tool_call, store, call_id, body.decision, body.final_args, body.decided_by,
                    body.reason)

    @app.get("/v1/roi", dependencies=[Depends(auth)])
    def roi() -> dict:
        return service.roi(store, cfg.roi_horizon_minutes)

    @app.websocket("/v1/stream")
    async def stream(ws: WebSocket) -> None:
        """Pushes new actions/verdicts/alerts/pending tool calls every second (optional client)."""
        await ws.accept()
        if cfg.api_token and ws.query_params.get("token") != cfg.api_token:
            await ws.close(code=4401)
            return
        seen: dict[str, int] = {"action": 0, "verdict": 0, "alert": 0, "tool_call": 0}
        sources = {"action": lambda: store.recent_actions(20), "verdict": lambda: store.recent_verdicts(20),
                   "alert": lambda: store.recent_alerts(20), "tool_call": lambda: store.list_tool_calls(limit=20)}
        try:
            while True:
                try:
                    batch = {kind: fetch() for kind, fetch in sources.items()}
                    fleet_rows = service.fleet_view(store)
                except Exception:  # a store hiccup must not kill the stream; try again next second
                    log.exception("stream: store read failed")
                    await asyncio.sleep(1.0)
                    continue
                for kind, rows in batch.items():
                    for row in sorted(rows, key=lambda r: r["id"]):
                        if row["id"] > seen[kind]:
                            seen[kind] = row["id"]
                            await ws.send_json({"type": kind, "data": row})
                await ws.send_json({"type": "metric", "data": fleet_rows})
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):  # client went away mid-send
            return

    return app
