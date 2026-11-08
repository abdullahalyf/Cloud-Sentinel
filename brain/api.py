"""
C2 (Command & Control) REST + WebSocket API (CONTRACTS §6). Interactive docs: http://localhost:8000/docs

Thin layer: validation + brain.service. The engine executes commands on its next tick.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from brain import service
from brain import audit as brain_audit
from brain import backtest as brain_backtest
from brain import cascade as brain_cascade
from brain import budget as brain_budget
from brain import explain as brain_explain
from brain import postmortem as brain_postmortem
from brain.policy import Policy
from brain.policy_reload import PolicyManager
from brain.policy_schema import validate_yaml as policy_schema_validate
from shared.config import Settings
from shared.contracts import (CONTRACT_VERSION, HEAL_DECISIONS, HEAL_STATUSES,
                              TOOL_DECISIONS, ToolRegistryRow, postmortem_markdown as postmortem_md,
                              security_report_view, security_tool, security_tools_view)

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


class ToolRegistryIn(BaseModel):
    """The tools a registry serves, with their descriptions (B8).

    A registry reports what it offers; the brain checks the descriptions for
    steering and tells the registry what it found.
    """
    registry: str = ""
    tools: list[dict[str, Any]] = Field(default_factory=list)
    reported_by: str = "mcp"


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


def _refresh_descriptions(gate, store) -> None:
    """
    Give the gate the descriptions the brain knows about.

    The gate checks a tool's description before it lets a call through, so it
    needs to know what the registries actually serve. Without this the gate would
    have nothing to check and a poisoned tool would sail through.

    A store that cannot be read must not take the endpoint down: a missing
    registry table is a missing verdict, not a failed report.
    """
    try:
        rows = store.list_tools(limit=1000)
    except Exception:
        return
    gate.descriptions = {r.get("tool_name", ""): r.get("description", "")
                         for r in rows if r.get("tool_name")}


def _burn_rates(store) -> dict[str, float]:
    """
    What each agent is burning right now, in $/min.

    It comes from the newest metric row per agent — the same number the
    dashboard shows. An agent with no recent metric burns nothing, and it is
    left out rather than reported as zero, so the forecast says nothing about
    it instead of claiming it will never run out.
    """
    rates: dict[str, float] = {}
    for row in store.recent_metrics(minutes=1):
        agent_id = row.get("agent_id")
        if not agent_id:
            continue
        try:
            rate = float(row.get("usd_per_min") or 0.0)
        except (TypeError, ValueError):
            continue
        if rate > 0:
            rates[agent_id] = rate
    return rates


def create_app(store, policy: Policy, cfg: Settings, mode: str, judge: str,
               policy_manager: Optional[PolicyManager] = None,
               injection_gate: Optional[service.InjectionGate] = None) -> FastAPI:
    app = FastAPI(title="CloudSentinel C2 API", version=f"contract-{CONTRACT_VERSION}",
                  description="Command & Control for AI agent fleets: observe, pause, heal, kill.")

    # A5: the policy in force. The manager knows the file, so the API can also reload it and
    # report the last error. Without a manager (a test, a script) the API still serves the
    # policy it was given.
    manager = policy_manager or PolicyManager(policy, cfg.policy_file, store=store,
                                               default_budget=cfg.default_budget_usd,
                                               audit_enabled=cfg.audit_enabled)

    # A6: the injection gate. It scores a tool call's arguments before the policy looks at them.
    gate = injection_gate or service.InjectionGate(
        deny_threshold=cfg.injection_deny_threshold,
        approval_threshold=cfg.injection_approval_threshold,
        allowed_hosts=cfg.injection_allowed_hosts,
        enabled=cfg.injection_enabled)

    # B8: the security gate. A poisoned tool description is denied, and a secret in the
    # arguments is redacted before the call is stored. Off by default: with the flag off
    # the detectors do not run at all and the old behaviour stands.
    security_gate = service.SecurityGate(
        deny_threshold=cfg.security_deny_threshold,
        enabled=cfg.security_enabled,
        redact_enabled=cfg.security_redact_enabled)

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

    # ── the budget tree (CONTRACTS §6, B4) ──
    @app.get("/v1/budgets", dependencies=[Depends(auth)])
    def budgets() -> dict:
        """
        The budget tree, with a forecast at every level (B4).

        The org → team → agent tree is what stops one runaway agent from
        eating the fleet's money: the agent overruns its own share, and the
        tree says so out loud.

        The forecast only speaks when it can. An agent that is burning nothing
        has no "exhausted in X minutes" — the answer would be a lie — so its
        forecast says nothing rather than something wrong.
        """
        burn_rates = _burn_rates(store)
        tree = brain_budget.tree_from_store(store, policy, cfg, agent_burn_rates=burn_rates,
                                            as_of=time.time())
        return tree.to_report()

    # ── the policy backtest (CONTRACTS §6, B5) ──
    @app.get("/v1/backtest", dependencies=[Depends(auth)])
    def backtest(policy_path: str = "", minutes: Optional[float] = None) -> dict:
        """
        What would the candidate policy have caught? (B5)

        The stored traces are replayed against the candidate policy and the report
        says three things: the catches, the false positives, and the money saved.

        The false positives are in the report on purpose. A backtest that shows only
        the catches is an advertisement, not a measurement — the operator needs to
        see what the candidate policy would have broken as well as what it would
        have saved.

        It is behind `CS_BACKTEST_ENABLED` (off by default): the replay reads every
        span in the window, and a measurement nobody asked for is a cost. With the
        flag off the endpoint does not exist — a 404, not an empty report.
        """
        if not cfg.backtest_enabled:
            raise HTTPException(404, "the backtest is off (CS_BACKTEST_ENABLED)")
        return brain_backtest.run_backtest_with_path(
            store, cfg, live_policy(), policy_path=policy_path, minutes=minutes)

    # ── the cascade (CONTRACTS §6, B6) ──
    @app.get("/v1/cascades", dependencies=[Depends(auth)])
    def cascades(minutes: Optional[float] = None) -> dict:
        """
        The chains where the agents keep each other running. (B6)

        The report says two things about each chain: **the whole chain** (every
        agent in it, and its role) and **the part that was actually stopped**.
        They are kept apart on purpose — an agent that was already dead, or one
        another worker owns, is in the chain and not in the contained list, and a
        report that collapsed the two would make the brain look like it stopped
        more than it did.

        It is behind `CS_CASCADE_ENABLED` (off by default): with the flag off
        the endpoint does not exist — a 404, not an empty report.
        """
        if not cfg.cascade_enabled:
            raise HTTPException(404, "the cascade detection is off (CS_CASCADE_ENABLED)")
        window = float(minutes if minutes is not None else cfg.cascade_window_minutes)
        return brain_cascade.cascades_from_store(store, minutes=window)

    # ── the audit chain (CONTRACTS §6, B7) ──
    @app.get("/v1/audit", dependencies=[Depends(auth)])
    def audit(limit: int = 200) -> dict:
        """
        The tamper-evident chain of every decision and every human action. (B7)

        Each entry carries the hash of the entry before it, so an edit in the
        middle breaks every link after it — and so does a deletion. The endpoint
        serves the chain **and** the verification of it: `valid` says whether the
        chain is intact, and `broken_at` names the entry that broke it.

        It is behind `CS_AUDIT_ENABLED` (off by default), but unlike the backtest
        and the cascade it does **not** disappear when the flag is off: an operator
        asking "is the log tamper-proof?" deserves an answer rather than a 404.

        The flag decides whether the chain is **written**, not whether it is
        **read**. So with the flag off the endpoint says `enabled: false` and
        serves whatever chain already exists — a chain written before the flag
        was turned off is still a chain, and hiding it would be the one thing a
        tamper-evident log must never do.
        """
        return brain_audit.chain_view(store, limit=clamp_limit(limit),
                                      enabled=cfg.audit_enabled, as_of=time.time())

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
                    body.base_version, gate, cfg.audit_enabled)

    @app.get("/v1/agents/{agent_id}/memory/history", dependencies=[Depends(auth)])
    def memory_history(agent_id: str, limit: int = 10) -> dict:
        return {"items": store.memory_history(agent_id, limit=clamp_limit(limit, 100))}

    @app.post("/v1/agents/{agent_id}/tool-calls", dependencies=[Depends(auth)])
    def tool_call(agent_id: str, body: ToolCallIn) -> dict:
        # the live policy, not the one from startup: A5 lets an operator change the rules
        # without a restart. The injection gate (A6) looks at the arguments first, and the
        # security gate (B8) denies a call to a tool whose description is poisoned.
        return call(service.request_tool_call, store, live_policy(), agent_id, body.tool_name, body.args,
                    body.value_usd, gate, cfg.audit_enabled, security_gate)

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
                    body.reason, cfg.audit_enabled)

    @app.get("/v1/tool-risk", dependencies=[Depends(auth)])
    def tool_risk(agent_id: Optional[str] = None) -> dict:
        """
        The learned tool risk (A14): what a human has approved, per (agent, tool, args).

        The counting rule is the shared one, so this endpoint and the mock's say the
        same thing about what counts as an approval.
        """
        from brain import tool_risk as brain_tool_risk

        return brain_tool_risk.learn(store, agent_id=agent_id)

    # ── the security detectors (CONTRACTS §6, B8) ──
    @app.post("/v1/security/tools", dependencies=[Depends(auth)])
    def report_security_tools(body: ToolRegistryIn) -> dict:
        """
        A registry reports the tools it serves (B8), and the brain checks the descriptions.

        A tool's *description* is what the agent reads before it decides, so a
        description that tries to steer the agent ("always call this first", "do
        not ask for approval") is an attack on the agent's instructions. The
        detector reads the descriptions the registry actually serves and says which
        ones are poisoned — and **why**, because a detector that only says "yes" is
        a detector nobody can tune.

        The verdict is stored, so the gate can deny a call to a poisoned tool. The
        description is kept as it was served, so a human can see what the registry
        actually said.

        With `CS_SECURITY_ENABLED` off the detectors do not run at all: the tools
        are recorded as they were reported, and every one of them is `clean`.
        """
        from brain import security as brain_security

        registry = (body.registry or "").strip() or "default"
        reported = []
        for tool in body.tools:
            name, description = brain_security.tool_name_and_description(tool)
            if not name:
                continue
            finding = None
            if cfg.security_enabled:
                finding = brain_security.scan_tool_description(name, description)
            status = "poisoned" if finding is not None else "clean"
            reasons = list(finding.reasons) if finding is not None else []
            score = float(finding.score) if finding is not None else 0.0
            store.upsert_tool(ToolRegistryRow(
                registry=registry, tool_name=name, description=description,
                reported_by=body.reported_by or "mcp", status=status,
                reasons="; ".join(reasons), score=score))
            reported.append(security_tool(
                tool_name=name, description=description, registry=registry,
                status=status, reasons=reasons, score=score,
                reported_by=body.reported_by or "mcp", updated_at=time.time()))
        # The gate learns what it just learned: the descriptions it must check
        # before it lets a call through.
        _refresh_descriptions(security_gate, store)
        return security_tools_view(tools=reported, enabled=cfg.security_enabled, as_of=time.time())

    @app.get("/v1/security/tools", dependencies=[Depends(auth)])
    def security_tools(registry: Optional[str] = None, status: Optional[str] = None) -> dict:
        """
        What the brain found in the tools the registries serve (B8).

        `status=poisoned` filters to the ones that tried to steer the agent — the
        question an operator asks first.

        The endpoint exists whether or not the detectors are on: an operator asking
        "is a tool poisoned?" deserves an answer rather than a 404, and a verdict
        written before the flag was turned off is still a verdict.
        """
        if status is not None and status not in ("clean", "poisoned"):
            raise HTTPException(400, "status must be clean or poisoned")
        rows = store.list_tools(registry=registry, status=status, limit=clamp_limit(500, 1000))
        tools = [security_tool(tool_name=r.get("tool_name", ""),
                               description=r.get("description", ""),
                               registry=r.get("registry", ""),
                               status=r.get("status", "clean"),
                               reasons=[x for x in (r.get("reasons") or "").split("; ") if x],
                               score=float(r.get("score") or 0.0),
                               reported_by=r.get("reported_by", "mcp"),
                               updated_at=r.get("updated_at"))
                 for r in rows]
        return security_tools_view(tools=tools, enabled=cfg.security_enabled, as_of=time.time())

    @app.get("/v1/security/report", dependencies=[Depends(auth)])
    def security_report() -> dict:
        """
        The findings of the last scan (B8): what fired, how bad it was, and **why**.

        The counts are the first thing an operator reads — "is anything poisoned" is
        a count, not a list.
        """
        rows = store.list_tools(limit=clamp_limit(500, 1000))
        findings = []
        for r in rows:
            if r.get("status") != "poisoned":
                continue
            reasons = [x for x in (r.get("reasons") or "").split("; ") if x]
            findings.append({
                "detector": "tool_description_poisoning",
                "severity": "critical" if len(reasons) > 1 else "warning",
                "title": f"the description of {r.get('tool_name')!r} is poisoned",
                "detail": f"{r.get('registry', '') or 'a registry'} serves a description "
                          "that tries to steer the agent",
                "subject": r.get("tool_name", ""),
                "score": float(r.get("score") or 0.0),
                "reasons": reasons,
            })
        return security_report_view(findings=findings, enabled=cfg.security_enabled, as_of=time.time())

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
        return call(service.decide_heal_proposal, store, proposal_id, decision, body.requested_by,
                    body.reason, cfg.audit_enabled)

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
