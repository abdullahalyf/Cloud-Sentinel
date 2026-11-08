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

It also shows the two **cascade** scenarios (B6) — alpha → beta → alpha, and delta flooding
gamma — so the dashboard can be built against a chain before the real brain has seen one.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from shared.contracts import (AUDIT_GENESIS, COMMAND_TYPES, CONTRACT_VERSION, HEAL_DECISIONS, HEAL_KINDS,
                              HEAL_STATUSES, ROGUE_KINDS,
                              ROI_FORMULA, TOOL_DECISIONS, ActionRow, AlertRow, HealProposalRow, MetricRow,
                              ToolCallRow, VerdictRow, agent_view, audit_entry, audit_hash, audit_view,
                              backtest_catch,
                              backtest_false_positive,
                              backtest_report, budget_forecast, budget_node, budget_report,
                              cascade_agent, cascade_edge, cascade_report, cascade_view,
                              explain_event, explain_report, load_json,
                              postmortem_event, postmortem_markdown, postmortem_report, postmortem_root_cause,
                              tool_risk_from_history, tool_risk_view, utc_now_iso)

AGENTS = ["alpha", "beta", "gamma", "delta"]
BUDGETS = {"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2}
# The teams the agents belong to (B4). The budget tree is org → team → agent,
# and every level is the sum of the level below it — so one runaway agent eats
# its own team's share, not the whole fleet's money.
TEAMS = {"alpha": "core", "beta": "core", "gamma": "ml", "delta": "ml"}
# The org budget is the sum of the team budgets, which are themselves the sum
# of their agents'. It is *computed*, never hand-set: a hand-set org budget
# would let the tree disagree with itself, and the tree is the whole point.
ORG_BUDGET = sum(BUDGETS.values())
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
HEAL_PROPOSALS: dict[int, dict] = {}
COMMANDS: list[dict] = []
ACTIONS: list[dict] = []
ALERTS: list[dict] = []


def seed() -> None:
    """(Re)fill the fake data in place. Called at import and by POST /v1/mock/reset (and tests)."""
    for coll in (MEMORY, TOOL_CALLS, HEAL_PROPOSALS, COMMANDS, ACTIONS, ALERTS, OVERRIDES):
        coll.clear()
    BUDGETS.update({"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2})
    MEMORY["beta"] = [{"id": 1, "agent_id": "beta", "version": 1, "edited_by": "agent", "reason": "",
                       "created_at": utc_now_iso(),
                       "content": {"order_4471": "orders API returned 500 - retry until success"}}]
    TOOL_CALLS[1] = ToolCallRow("delta", "issue_refund", {"order_id": 4471, "amount": 50000}, "pending", {}, "",
                                "refunds over 5,000 BDT need a human", 410.0).to_row() | {
        "id": 1, "args": {"order_id": 4471, "amount": 50000}, "final_args": {}}
    # A14: a human has approved the *same* small refund five times, so the sixth one
    # would be auto-approved. The mock shows both sides of the line: this call is past
    # the threshold, the one below it is not.
    for i in range(2, 7):
        TOOL_CALLS[i] = ToolCallRow("delta", "issue_refund", {"order_id": 9001, "amount": 1000}, "allow",
                                    {"order_id": 9001, "amount": 1000}, "human",
                                    "a small refund, the same one as last time", 12.0).to_row() | {
            "id": i, "args": {"order_id": 9001, "amount": 1000},
            "final_args": {"order_id": 9001, "amount": 1000}}
    TOOL_CALLS[7] = ToolCallRow("delta", "issue_refund", {"order_id": 9100, "amount": 2000}, "allow",
                                {"order_id": 9100, "amount": 2000}, "human",
                                "another small refund", 24.0).to_row() | {
        "id": 7, "args": {"order_id": 9100, "amount": 2000},
        "final_args": {"order_id": 9100, "amount": 2000}}
    # one pending heal proposal for beta, so the approvals inbox has something in it
    # the real API decodes the JSON `patch` column, so the mock serves a decoded patch too
    _proposal = HealProposalRow(
        "beta", "memory_patch",
        {"memory": [{"op": "set", "key": "order_4471", "value": "cancelled - skip it and move on"}]},
        0.71, "pending", 1, 1,
        "The belief 'retry until success' keeps the agent looping on a failing order",
    ).to_row()
    HEAL_PROPOSALS[1] = _proposal | {"id": 1, "patch": load_json(_proposal["patch"])}
    ACTIONS.extend([
        ActionRow("beta", "PAUSE", "claude", "semantic loop on order 4471", 2.52, 210000).to_row() | {"id": 2},
        ActionRow("gamma", "KILL", "rules", "Hard limit: 80,816 tokens/min", 129.6, 4800000).to_row() | {"id": 1}])
    ALERTS.append(AlertRow("beta", "warning", "loop_semantic,injection", "semantic loop score 0.85").to_row() | {"id": 1})


seed()


def _baseline(agent: str) -> dict:
    """A learned baseline per agent (A4): {metric: {median, limit, samples}}."""
    base = {"alpha": 4000, "beta": 3500, "gamma": 5000, "delta": 2500}[agent]
    return {
        "tokens_per_min": {"median": base, "limit": int(base * 1.6), "samples": 120},
        "usd_per_min": {"median": round(base * 4e-6, 5), "limit": round(base * 6.4e-6, 5), "samples": 120},
        "calls_per_sec": {"median": 0.2, "limit": 0.8, "samples": 120},
    }


def _fleet() -> list[dict]:
    now = time.time()
    out = []
    for a in AGENTS:
        m = _metric(a, now)
        row = {"agent_id": a, "display_name": a, "runtime": "mock", "state": _state(a), "budget_usd": BUDGETS[a],
               "spend_usd": m["spend_usd"], "total_tokens": m["total_tokens"], "baseline": _baseline(a),
               "updated_at": utc_now_iso()}
        out.append(agent_view(row, m, _verdict() if a == "beta" and _state(a) != "healthy" else None))
    return out


app = FastAPI(title="CloudSentinel MOCK C2 API", version=f"contract-{CONTRACT_VERSION}")


@app.get("/v1/health")
def health() -> dict:
    # A8: the workers the fleet is shared between. The mock has none — it serves one
    # brain — but the shape must be the same, so a client written against the mock
    # works against the real API.
    return {"ok": True, "mode": "mock", "judge": "claude", "contract": CONTRACT_VERSION,
            "workers": [], "agents_total": len(_fleet())}


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


@app.get("/v1/agents/{agent_id}/explain")
def explain(agent_id: str, minutes: float = 10) -> dict:
    """What happened to this agent, and why (A13).

    The story is built from the same fake events the mock already serves: the alert,
    the verdict, the action and the heal proposal. The *text* comes from
    `shared.contracts.explain_report`, so the mock and the real API say exactly the
    same thing — that is what the golden-text test compares.
    """
    view = next((a for a in _fleet() if a["agent_id"] == agent_id), None)
    if view is None:
        _bad(404, f"agent {agent_id} not found")
    now = time.time()
    events: list[dict] = []
    for a in ALERTS:
        if a.get("agent_id") == agent_id:
            events.append(explain_event("alert", now - 30, "rules flagged it", a.get("message", "")))
    verdict = _verdict()
    if agent_id == verdict["agent_id"]:
        events.append(explain_event("verdict", now - 20, verdict["action"], verdict["reason"]))
    for act in ACTIONS:
        if act.get("agent_id") == agent_id:
            events.append(explain_event("action", now - 10, act["action"], act.get("reason", "")))
    for p in HEAL_PROPOSALS.values():
        if p.get("agent_id") == agent_id:
            events.append(explain_event("heal", now - 5, p.get("kind", "patch"), p.get("reason", "")))
    events.sort(key=lambda e: e["ts"])
    saved = sum(float(a.get("saved_usd") or 0) for a in ACTIONS if a.get("agent_id") == agent_id)
    return explain_report(agent_id, view["state"], events, minutes=minutes,
                           spend_usd=view["spend_usd"], budget_usd=view["budget_usd"], saved_usd=saved)


@app.get("/v1/incidents/{incident_id}/postmortem")
def postmortem(incident_id: int) -> dict:
    """The postmortem of one incident (B2).

    An incident *is* an alert: the moment the brain flagged an agent and said
    "something is wrong here". The verdict, the action and the heal that followed
    are part of that incident, so the incident id is the alert id.

    The shape comes from `shared.contracts.postmortem_report`, so the mock and the
    real API say exactly the same thing — that is what the parity test compares.
    """
    alert = next((a for a in ALERTS if int(a.get("id") or 0) == int(incident_id)), None)
    if alert is None:
        _bad(404, f"incident {incident_id} not found")
    return _postmortem_for(alert)


def _postmortem_for(alert: dict) -> dict:
    """The postmortem of one alert, built from the mock's fake events."""
    agent_id = str(alert.get("agent_id") or "")
    now = time.time()
    # The alert is the incident. The evidence is the span-ish moment just before it.
    detected_at = now - 30.0
    timeline = [
        postmortem_event("evidence", detected_at - 10.0, "the agent started repeating itself",
                         "the same intent, 14 times in 60s", ref="mock-evidence"),
        postmortem_event("alert", detected_at, str(alert.get("rule") or "flagged"),
                         str(alert.get("message") or ""), ref=str(alert.get("id"))),
    ]
    verdict = _verdict()
    if verdict["agent_id"] == agent_id:
        timeline.append(postmortem_event("verdict", detected_at + 10.0, verdict["action"],
                                         verdict["reason"], ref=str(verdict.get("id"))))
    for act in ACTIONS:
        if act.get("agent_id") == agent_id:
            timeline.append(postmortem_event("action", detected_at + 20.0, str(act.get("action") or "?"),
                                             str(act.get("reason") or ""), ref=str(act.get("id"))))
    for p in HEAL_PROPOSALS.values():
        if p.get("agent_id") == agent_id:
            timeline.append(postmortem_event("heal", detected_at + 25.0, str(p.get("kind") or "patch"),
                                             str(p.get("reason") or ""), ref=str(p.get("id"))))

    saved = sum(float(a.get("usd_saved_estimate") or 0) for a in ACTIONS
                if a.get("agent_id") == agent_id and a.get("action") in ("KILL", "PAUSE"))
    tokens = sum(int(a.get("tokens_saved_estimate") or 0) for a in ACTIONS
                 if a.get("agent_id") == agent_id and a.get("action") in ("KILL", "PAUSE"))
    view = next((a for a in _fleet() if a["agent_id"] == agent_id), {})
    return postmortem_report(
        int(alert.get("id") or 0), agent_id,
        postmortem_root_cause(str(alert.get("rule") or ""), verdict.get("pattern", ""),
                              verdict.get("reason", ""), detector=verdict.get("source", "rules")),
        timeline,
        [{"span_id": "mock-span-0001", "trace_id": "mock-trace-0001",
          "operation": "chat", "start_ts": detected_at - 10.0}],
        {"usd_saved": saved, "tokens_saved": tokens, "spend_usd": view.get("spend_usd", 0.0)},
        {"time_to_detect_seconds": 10.0, "time_to_heal_seconds": 20.0,
         "detected_at": detected_at, "healed_at": detected_at + 20.0},
        resolution=f"{agent_id} was {str(alert.get('rule') or 'flagged')} and the brain stepped in.",
    )


@app.get("/v1/incidents/{incident_id}/postmortem.md")
def postmortem_markdown_endpoint(incident_id: int) -> str:
    """The same postmortem, as markdown."""
    alert = next((a for a in ALERTS if int(a.get("id") or 0) == int(incident_id)), None)
    if alert is None:
        _bad(404, f"incident {incident_id} not found")
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(postmortem_markdown(_postmortem_for(alert)),
                             media_type="text/markdown; charset=utf-8")


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


# ── policy (CONTRACTS §6, added 8 Nov) ──
POLICY_SOURCE = "brain/policies.yaml"


def _policy_view() -> dict:
    """
    The mock serves the real policy file, so the dashboard shows the same rules.

    The mock must work on its own (dashboard development, no brain), so it falls back to
    reading the YAML directly when the brain is not importable.
    """
    try:
        from brain.policy import Policy

        p = Policy.load(POLICY_SOURCE)
        return p.to_dict() | {"source": POLICY_SOURCE, "last_error": ""}
    except Exception:
        pass
    try:
        import yaml

        data = yaml.safe_load(Path(POLICY_SOURCE).read_text(encoding="utf-8")) or {}
        defaults = data.get("defaults") or {}
        return {"version": "mock", "loaded_at": utc_now_iso(), "source": POLICY_SOURCE,
                "defaults": {"budget_usd": defaults.get("budget_usd", 0.5),
                             "on_trip": defaults.get("on_trip", "pause"),
                             "on_hard_limit": defaults.get("on_hard_limit", "kill")},
                "agents": data.get("agents") or {}, "tools": data.get("tools") or [], "last_error": ""}
    except Exception as exc:
        return {"version": "unknown", "loaded_at": utc_now_iso(), "source": POLICY_SOURCE,
                "defaults": {}, "agents": {}, "tools": [], "last_error": str(exc)}


@app.get("/v1/policy")
def policy() -> dict:
    return _policy_view()


@app.post("/v1/policy/reload")
def policy_reload() -> dict:
    """The mock has no engine to reload: it just re-reads the file."""
    return {"ok": True, "policy": _policy_view()}


@app.post("/v1/policy/validate")
def policy_validate(body: dict[str, Any]) -> dict:
    """Validate a YAML policy without touching the running one."""
    try:
        from brain.policy_schema import validate_yaml

        errors = validate_yaml(str(body.get("yaml") or ""))
    except Exception as exc:
        errors = [f"policy: {exc}"]
    return {"ok": not errors, "errors": errors}


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


@app.get("/v1/tool-risk")
def tool_risk(agent_id: Optional[str] = None) -> dict:
    """
    The learned tool risk (A14): what a human has approved, per (agent, tool, args).

    The mock leads the real API here — the contract lands the mock first, and the brain
    branch follows. The counting is done by `shared.contracts.tool_risk_from_history`, the
    same function the real API uses, so the two cannot drift on what counts as an approval.
    """
    calls = list(TOOL_CALLS.values())
    if agent_id:
        calls = [c for c in calls if c.get("agent_id") == agent_id]
    entries = tool_risk_from_history(calls)
    return tool_risk_view(entries)


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


# ── auto-heal proposals (CONTRACTS §7) ──
@app.get("/v1/heal-proposals")
def heal_proposals(status: Optional[str] = None, agent_id: Optional[str] = None, limit: int = 50) -> dict:
    if status is not None and status not in HEAL_STATUSES:
        _bad(400, f"status must be one of {', '.join(HEAL_STATUSES)}")
    rows = sorted(HEAL_PROPOSALS.values(), key=lambda p: -p["id"])
    rows = [p for p in rows if status is None or p["status"] == status]
    rows = [p for p in rows if agent_id is None or p["agent_id"] == agent_id]
    return {"items": rows[:max(1, limit)]}


@app.get("/v1/heal-proposals/{proposal_id}")
def get_heal_proposal(proposal_id: int) -> dict:
    if proposal_id not in HEAL_PROPOSALS:
        _bad(404, f"heal proposal {proposal_id} not found")
    return HEAL_PROPOSALS[proposal_id]


@app.post("/v1/heal-proposals/{proposal_id}/decision")
def decide_heal_proposal(proposal_id: int, body: dict[str, Any]) -> dict:
    decision = str(body.get("decision", "")).lower()
    if decision not in HEAL_DECISIONS:
        _bad(400, f"decision must be one of {', '.join(HEAL_DECISIONS)}")
    requested_by = body.get("requested_by", "human")
    if requested_by not in ("human", "mcp"):
        _bad(400, "requested_by must be one of human, mcp")
    proposal = HEAL_PROPOSALS.get(proposal_id)
    if proposal is None:
        _bad(404, f"heal proposal {proposal_id} not found")
    if proposal["status"] != "pending":
        _bad(409, f"heal proposal {proposal_id} already decided: {proposal['status']}")
    if decision == "apply":
        # the mock applies the memory patch to beta's memory, like the real brain does
        versions = MEMORY.setdefault(proposal["agent_id"], [])
        content = dict(versions[-1]["content"]) if versions else {}
        for op in load_json(proposal.get("patch") or {}).get("memory", []):
            if op.get("op") == "remove":
                content.pop(op.get("key", ""), None)
            else:
                content[op.get("key", "")] = op.get("value")
        versions.append({"id": sum(len(v) for v in MEMORY.values()) + 1, "agent_id": proposal["agent_id"],
                         "version": (versions[-1]["version"] + 1) if versions else 1, "content": content,
                         "edited_by": "mcp" if requested_by == "mcp" else "human",
                         "reason": body.get("reason") or "heal applied", "created_at": utc_now_iso()})
        status, actor = "applied", "brain:autoheal" if requested_by == "mcp" else "human"
    else:
        status, actor = "rejected", "brain:autoheal" if requested_by == "mcp" else "human"
    proposal.update(status=status, decided_by=actor, reason=body.get("reason", ""), decided_at=utc_now_iso())
    _action(proposal["agent_id"], "AUTO_HEAL" if decision == "apply" else "WARN", actor,
            body.get("reason") or f"heal proposal {decision}")
    return proposal


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


@app.get("/v1/budgets")
def budgets() -> dict:
    """
    The budget tree (B4): org → team → agent, with a forecast at every level.

    The tree is the point — **the org's budget is the sum of the teams', and a
    team's is the sum of its agents'** — so one runaway agent eats its own
    share first and the rest of the fleet's money is still there.
    """
    fleet = {row["agent_id"]: row for row in _fleet()}
    now = time.time()

    agents = []
    for agent_id in AGENTS:
        row = fleet.get(agent_id, {})
        spend = float(row.get("spend_usd") or 0.0)
        budget = float(BUDGETS.get(agent_id, 0.0))
        # The mock's burn rate is a fixed number, so the forecast is a function
        # of the spend and never changes from one call to the next.
        burn = 0.002
        agents.append(budget_node("agent", agent_id, budget, spend,
                                  forecast=budget_forecast(budget, spend, burn)))

    teams = []
    for team_id in sorted(set(TEAMS.values())):
        members = [a for a in AGENTS if TEAMS.get(a) == team_id]
        budget = sum(BUDGETS.get(a, 0.0) for a in members)
        spend = sum(float(fleet.get(a, {}).get("spend_usd") or 0.0) for a in members)
        teams.append(budget_node("team", team_id, budget, spend,
                                 children=[a["id"] for a in agents if a["id"] in members],
                                 forecast=budget_forecast(budget, spend, 0.002 * len(members))))

    org_spend = sum(float(row.get("spend_usd") or 0.0) for row in fleet.values())
    org = budget_node("org", "org", ORG_BUDGET, org_spend,
                      children=[t["id"] for t in teams],
                      forecast=budget_forecast(ORG_BUDGET, org_spend, 0.002 * len(AGENTS)))
    return budget_report(org, teams, agents, as_of=now)


@app.get("/v1/backtest")
def backtest(policy_path: str = "") -> dict:
    """
    The policy backtest (B5): what would the candidate policy have caught?

    The mock has no spans to replay, so the numbers are **fixed** — a mock whose
    backtest drifts with the clock would be useless for building a dashboard
    against. What the mock does show is the *shape*: catches, false positives,
    and the money saved, all from the same builder the real API uses.

    The story the fake data tells: beta looped and was paused, gamma broke a hard
    limit and was killed — the running policy caught both. A *tighter* candidate
    policy would also have stopped alpha and delta, which were perfectly fine.
    Those are the false positives, and they are in the report on purpose.
    """
    now = time.time()
    catches = [
        backtest_catch("loop_semantic", "beta", now - 420.0, "PAUSE",
                       "semantic loop score 0.85 on order 4471", 2.52),
        backtest_catch("token_rate_hard", "gamma", now - 300.0, "KILL",
                       "80,816 tokens/min ≥ hard limit", 129.6),
    ]
    false_positives = [
        backtest_false_positive("budget_80pct", "alpha", now - 240.0,
                                "82% of budget used, but the agent was healthy"),
        backtest_false_positive("call_spike", "delta", now - 180.0,
                                "1.4 calls/s ≥ the candidate's soft limit of 1.0"),
    ]
    return backtest_report(catches=catches, false_positives=false_positives,
                           policy_version="mockpolicy01", agents_tested=list(AGENTS),
                           spans_replayed=1284, usd_saved=2.52 + 129.6,
                           horizon_minutes=60.0, as_of=now)


@app.get("/v1/cascades")
def cascades() -> dict:
    """
    The cascades (B6): the chains where agents keep each other running.

    The mock has no spans to walk, so the cascades are **fixed** — a mock whose
    cascades drifted with the clock would be useless for building a dashboard
    against. What the mock does show is the *shape* and the two kinds:

    - a **loop** — alpha calls beta calls alpha. Two agents, each holding the
      other up, so pausing one of them would only move the problem.
    - a **contagion** — delta floods gamma, and gamma's own spike is a symptom.

    Both cascades show the whole chain in `agents` and the part that was
    actually stopped in `contained`, because the two are different facts: the
    chain is bigger than the part the brain got to.
    """
    now = time.time()
    loop_cascade = cascade_report(
        kind="loop",
        cascade_id="loop-alpha-beta",
        agents=[cascade_agent("alpha", "source", "calls beta, and beta calls it back"),
                cascade_agent("beta", "member", "calls alpha, and alpha calls it back")],
        edges=[cascade_edge("alpha", "beta", calls=14),
               cascade_edge("beta", "alpha", calls=12)],
        contained=["alpha", "beta"],
        detected_at=now - 90.0,
        reason="alpha → beta → alpha: two agents keeping each other running",
        usd_saved=4.18)
    contagion = cascade_report(
        kind="contagion",
        cascade_id="contagion-delta-gamma",
        agents=[cascade_agent("delta", "source", "floods gamma with 60 calls in a minute"),
                cascade_agent("gamma", "target", "its own spike is a symptom of delta")],
        edges=[cascade_edge("delta", "gamma", calls=60)],
        contained=["delta"],
        detected_at=now - 45.0,
        reason="delta flooded gamma: 60 calls into one agent in a minute",
        usd_saved=1.02)
    return cascade_view(cascades=[contagion, loop_cascade], as_of=now)


@app.get("/v1/audit")
def audit(limit: int = 200) -> dict:
    """
    The tamper-evident audit chain (B7).

    Every decision and every human action goes into a **hash-chained** log: each
    entry carries the hash of the entry before it, so an edit in the middle
    breaks every link after it — and so does a deletion.

    The mock has no brain behind it, so the chain is **fixed**. But the hashes
    are **real**: the mock builds the chain with the same rule the brain uses,
    so a client written against the mock can verify the mock's chain the same
    way it verifies the real one. A mock with fake hashes would teach the
    client to skip the check.

    The chain shows the three kinds of thing that goes into it:
    - a **decision** the brain took on its own (a runaway paused);
    - a **human** action (an operator pausing an agent by hand);
    - a **policy** action (the tool gate denying a call).
    """
    now = time.time()
    steps = [
        ("decision", "rules", "beta", "PAUSE", "semantic loop on order 4471"),
        ("human", "dashboard", "beta", "PAUSE", "an operator paused it by hand"),
        ("policy", "policy", "delta", "TOOL_DENY", "issue_refund: $41,000 is over the limit"),
        ("decision", "brain:autoheal", "beta", "AUTO_HEAL", "the belief keeps it looping"),
        ("human", "mcp", "gamma", "SET_BUDGET", "budget set to $2.00"),
    ]
    entries: list[dict] = []
    prev = AUDIT_GENESIS
    for seq, (kind, actor, agent_id, action, reason) in enumerate(steps, start=1):
        entry = audit_entry(seq=seq, agent_id=agent_id, kind=kind, actor=actor,
                            action=action, reason=reason, prev_hash=prev,
                            created_at=now - (len(steps) - seq) * 30.0)
        entry["hash"] = audit_hash(entry)
        entries.append(entry)
        prev = entry["hash"]
    return audit_view(entries=entries, head_hash=prev, valid=True, broken_at=None,
                      enabled=True, as_of=now)


if __name__ == "__main__":
    import uvicorn

    print("MOCK CloudSentinel API on http://localhost:8000  (docs: /docs)")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
