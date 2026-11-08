"""
C2 (Command & Control) REST + WebSocket API (CONTRACTS §6). Interactive docs: http://localhost:8000/docs

Thin layer: validation + brain.service. The engine executes commands on its next tick.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from brain import service
from brain import explain as brain_explain
from brain import postmortem as brain_postmortem
from brain.policy import Policy
from brain.policy_reload import PolicyManager
from brain.policy_schema import validate_yaml as policy_schema_validate
from shared.config import Settings
from shared.contracts import (CONTRACT_VERSION, HEAL_DECISIONS, HEAL_STATUSES,
                              TOOL_DECISIONS, postmortem_markdown as postmortem_md)

log = logging.getLogger("brain.api")


class CommandIn(BaseModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "dashboard"
    reason: str = ""


class PolicyValidateIn(BaseModel):
    yaml: str = ""


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


class HealDecisionIn(BaseModel):
    decision: str
    reason: str = ""
    requested_by: str = "human"


def clamp_limit(limit: int, top: int = 1000) -> int:
    return max(1, min(int(limit), top))


def clamp_minutes(minutes: float, top: float = 24 * 60) -> float:
    return max(0.1, min(float(minutes), top)) if minutes == minutes else 5.0  # NaN → default


def create_app(store, policy: Policy, cfg: Settings, mode: str, judge: str,
               policy_manager: Optional[PolicyManager] = None,
               injection_gate: Optional[service.InjectionGate] = None) -> FastAPI:
    app = FastAPI(title="CloudSentinel C2 API", version=f"contract-{CONTRACT_VERSION}",
                  description="Command & Control for AI agent fleets: observe, pause, heal, kill.")

    # A5: the policy in force. The manager knows the file, so the API can also reload it and
    # report the last error. Without a manager (a test, a script) the API still serves the
    # policy it was given.
    manager = policy_manager or PolicyManager(policy, cfg.policy_file, store=store,
                                               default_budget=cfg.default_budget_usd)

    # A6: the injection gate. It scores a tool call's arguments before the policy looks at them.
    gate = injection_gate or service.InjectionGate(
        deny_threshold=cfg.injection_deny_threshold,
        approval_threshold=cfg.injection_approval_threshold,
        allowed_hosts=cfg.injection_allowed_hosts,
        enabled=cfg.injection_enabled)

    def live_policy() -> Policy:
        """The policy that is in force right now (it can change under us — A5)."""
        return manager.policy

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        """CONTRACTS §6: client errors are 400 with a readable {"detail": "..."} (not FastAPI's 422 list)."""
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
        return JSONResponse({"detail": f"{where}: {first.get('msg', 'invalid request')}"}, status_code=400)

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
        # A8: the workers the fleet is shared between. A store that cannot say (an old
        # Supabase schema) must not take the whole health check down — the brain is up,
        # and that is what a health check is for.
        #
        # Every worker in the table is listed, alive or not. Deciding who is alive is the
        # shard's job (it knows its own clock); a health check that filtered on the
        # store's wall clock would disagree with the workers about who is dead.
        try:
            workers = store.list_workers()
        except Exception:
            workers = []
        return {"ok": True, "mode": mode, "judge": judge, "contract": CONTRACT_VERSION,
                "workers": workers, "agents_total": len(service.fleet_view(store))}

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

    @app.get("/v1/agents/{agent_id}/nodes", dependencies=[Depends(auth)])
    def nodes(agent_id: str, minutes: float = 10, limit: int = 100) -> dict:
        return service.node_feed(store, agent_id, clamp_minutes(minutes), clamp_limit(limit, 500))

    @app.get("/v1/agents/{agent_id}/explain", dependencies=[Depends(auth)])
    def explain(agent_id: str, minutes: float = 10) -> dict:
        """
        What happened to this agent, and why (A13).

        The summary is deterministic — no key, no network. The Claude polish is an
        extra: when there is a key it fills in `polished_summary`, and when there is
        not, `polished_summary` stays null and `summary` is the whole answer. A slow
        third-party call must not be able to take this endpoint down, so the polish
        happens after the deterministic report is already built, and any failure in it
        is swallowed.

        An agent that does not exist is a 404, the way the mock answers it: an
        explanation of nothing would be a confident paragraph about an agent nobody
        has ever heard of.
        """
        report = brain_explain.build_explanation(store, agent_id, minutes=clamp_minutes(minutes))
        if report is None:
            raise HTTPException(404, f"agent {agent_id} not found")
        if judge != "fallback" and report.get("summary"):
            report = brain_explain.polish(report, cfg=cfg)
        return report

    # ── the incident postmortem (CONTRACTS §6, B2) ──
    @app.get("/v1/incidents/{incident_id}/postmortem", dependencies=[Depends(auth)])
    def postmortem(incident_id: int) -> dict:
        """
        The postmortem of one incident (B2).

        An incident *is* an alert — the moment the brain flagged an agent — so
        the incident id is the alert id. An id no alert ever had is a 404, the
        way the mock answers it: a postmortem of nothing would be a confident
        account of a thing that never happened.
        """
        report = brain_postmortem.build_postmortem(store, incident_id)
        if report is None:
            raise HTTPException(404, f"incident {incident_id} not found")
        return report

    @app.get("/v1/incidents/{incident_id}/postmortem.md", dependencies=[Depends(auth)])
    def postmortem_markdown(incident_id: int) -> PlainTextResponse:
        """
        The same postmortem, as markdown.

        The markdown renders the JSON and never recomputes it, so the two
        endpoints can never disagree about a number.
        """
        report = brain_postmortem.build_postmortem(store, incident_id)
        if report is None:
            raise HTTPException(404, f"incident {incident_id} not found")
        return PlainTextResponse(postmortem_md(report),
                                 media_type="text/markdown; charset=utf-8")

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
        return call(service.save_memory, store, agent_id, body.content, body.edited_by, body.reason,
                    body.base_version, gate)

    @app.get("/v1/agents/{agent_id}/memory/history", dependencies=[Depends(auth)])
    def memory_history(agent_id: str, limit: int = 10) -> dict:
        return {"items": store.memory_history(agent_id, limit=clamp_limit(limit, 100))}

    @app.post("/v1/agents/{agent_id}/tool-calls", dependencies=[Depends(auth)])
    def tool_call(agent_id: str, body: ToolCallIn) -> dict:
        # the live policy, not the one from startup: A5 lets an operator change the rules
        # without a restart. The injection gate (A6) looks at the arguments first.
        return call(service.request_tool_call, store, live_policy(), agent_id, body.tool_name, body.args,
                    body.value_usd, gate)

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

    @app.get("/v1/tool-risk", dependencies=[Depends(auth)])
    def tool_risk(agent_id: Optional[str] = None) -> dict:
        """
        The learned tool risk (A14): what a human has approved, per (agent, tool, args).

        The counting rule is the shared one, so this endpoint and the mock's say the
        same thing about what counts as an approval.
        """
        from brain import tool_risk as brain_tool_risk

        return brain_tool_risk.learn(store, agent_id=agent_id)

    @app.get("/v1/roi", dependencies=[Depends(auth)])
    def roi() -> dict:
        return service.roi(store, cfg.roi_horizon_minutes)

    # ── policy (CONTRACTS §11) ──
    @app.get("/v1/policy", dependencies=[Depends(auth)])
    def get_policy() -> dict:
        """The policy that is in force right now."""
        return manager.view()

    @app.post("/v1/policy/reload", dependencies=[Depends(auth)])
    def reload_policy() -> dict:
        """Re-read the policy file now, whether or not it changed."""
        result = manager.reload_now()
        return {"ok": result.loaded or not result.changed, "policy": manager.view(),
                "errors": result.errors, "summary": result.summary}

    @app.post("/v1/policy/validate", dependencies=[Depends(auth)])
    def validate_policy(body: PolicyValidateIn) -> dict:
        """Check a policy file's text. Changes nothing."""
        errors = policy_schema_validate(body.yaml or "")
        return {"ok": not errors, "errors": errors}

    # ── auto-heal proposals (CONTRACTS §7) ──
    @app.get("/v1/heal-proposals", dependencies=[Depends(auth)])
    def heal_proposals(status: Optional[str] = None, agent_id: Optional[str] = None,
                       limit: int = 50) -> dict:
        if status is not None and status not in HEAL_STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(HEAL_STATUSES)}")
        return {"items": service.list_heal_proposals(store, status, agent_id, clamp_limit(limit))}

    @app.get("/v1/heal-proposals/{proposal_id}", dependencies=[Depends(auth)])
    def get_heal_proposal(proposal_id: int) -> dict:
        row = store.get_heal_proposal(proposal_id)
        if row is None:
            raise HTTPException(404, f"heal proposal {proposal_id} not found")
        return row

    @app.post("/v1/heal-proposals/{proposal_id}/decision", dependencies=[Depends(auth)])
    def decide_heal_proposal(proposal_id: int, body: HealDecisionIn) -> dict:
        decision = (body.decision or "").strip().lower()
        if decision not in HEAL_DECISIONS:
            raise HTTPException(400, f"decision must be one of {', '.join(HEAL_DECISIONS)}")
        return call(service.decide_heal_proposal, store, proposal_id, decision, body.requested_by, body.reason)

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
