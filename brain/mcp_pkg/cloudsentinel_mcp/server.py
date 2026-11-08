"""
CloudSentinel MCP server — the packaged version (A7).

Every tool calls the C2 REST API, so it also works against the mock API.

    cloudsentinel-mcp --help
    cloudsentinel-mcp                       # stdio (Claude Desktop / Claude Code)
    cloudsentinel-mcp --http --port 8765    # Streamable HTTP

Hardening (A7):
  * every argument is validated before it reaches the API — the caller gets a clear
    message, never a stack trace
  * destructive calls are rate limited per session (CS_MCP_RATE_LIMIT, default 30/min)
  * --http refuses to bind a non-localhost address unless CS_API_TOKEN is set, and then
    demands "Authorization: Bearer <token>"
  * CS_MCP_READONLY=true exposes only the tools that change nothing

The annotations are audited: `readOnlyHint` and `destructiveHint` must agree with the
READ_ONLY / DESTRUCTIVE sets below, and `brain/tests/test_mcp.py` checks that they do.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .client import ApiClient
from .config import McpSettings, load_settings
from .hardening import (RateLimiter, ToolError, check_agent_id, check_choice, check_content,
                        check_number, check_positive_id, check_reason, check_yaml)

SAFE = ToolAnnotations(read_only_hint=True, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

# The audited split. A tool that changes the fleet is destructive; one that only reads is
# safe. `brain/tests/test_mcp.py` asserts every registered tool matches its set.
DESTRUCTIVE_TOOLS = frozenset({
    "pause_agent", "resume_agent", "kill_agent", "set_budget", "edit_memory",
    "decide_tool_call", "decide_heal",
})
READ_ONLY_TOOLS = frozenset({
    "list_agents", "get_agent", "explain_agent", "get_memory", "list_pending_tool_calls",
    "get_roi_report", "get_policy", "validate_policy", "list_heal_proposals",
})

settings: McpSettings = load_settings()
client = ApiClient(settings.api_url, settings.api_token)
limiter = RateLimiter(limit=settings.rate_limit_per_min)

mcp = MCPServer("cloudsentinel", instructions=(
    "CloudSentinel is a circuit breaker for AI agents. Use list_agents first. Prefer pause_agent over "
    "kill_agent: a paused agent keeps its state and can be healed with edit_memory and resumed. "
    "Always give a short reason; it is written to the audit log."))


# ── guards ───────────────────────────────────────────────────────────────────
def _guard_rate_limit() -> None:
    """Destructive calls only. Reading the fleet is free — a dashboard should not be throttled."""
    allowed, why = limiter.allow()
    if not allowed:
        raise ToolError(why)


def _guard_write() -> None:
    """Refuse a write in read-only mode, before the rate limiter spends a slot."""
    if settings.readonly:
        raise ToolError("this server is in read-only mode (CS_MCP_READONLY=true); "
                        "it can look at the fleet but not change it")


def _agent_path(agent_id: Any) -> str:
    return f"/v1/agents/{check_agent_id(agent_id)}"


def _command(agent_id: Any, command: str, reason: Any, params: Optional[dict] = None) -> dict:
    _guard_write()
    _guard_rate_limit()
    path = _agent_path(agent_id)
    body = {"command": command, "params": params or {}, "requested_by": "mcp",
            "reason": check_reason(reason, required=(command != "SET_BUDGET"))}
    result = client.post(f"{path}/commands", body)
    return {**result, "note": "The engine executes commands within ~1 second. Check with get_agent."}


# ── read tools ───────────────────────────────────────────────────────────────
@mcp.tool(annotations=SAFE)
def list_agents() -> list[dict]:
    """List every agent with its breaker state, spend rate ($/min), spend vs budget and loop score."""
    agents = client.get("/v1/fleet")["agents"]
    return [{k: a.get(k) for k in ("agent_id", "state", "usd_per_min", "spend_usd", "budget_usd",
                                   "tokens_per_min", "loop_score", "exact_repeats", "memory_pct")}
            for a in agents]


@mcp.tool(annotations=SAFE)
def get_agent(agent_id: str) -> dict:
    """Full details of one agent: metrics, last judge verdicts and current memory."""
    data = client.get(_agent_path(agent_id))
    return {"agent": data["agent"], "verdicts": data.get("verdicts", [])[:3],
            "memory": data.get("memory")}


@mcp.tool(annotations=SAFE)
def explain_agent(agent_id: str) -> str:
    """Plain-English explanation of why an agent is in its current state."""
    data = client.get(_agent_path(agent_id))
    agent, verdicts = data["agent"], data.get("verdicts", [])
    text = (f"{agent['agent_id']} is {agent['state'].upper()}. "
            f"Spending ${float(agent.get('usd_per_min') or 0):.4f}/min, "
            f"${float(agent.get('spend_usd') or 0):.3f} of ${float(agent.get('budget_usd') or 0):.2f} "
            f"budget. Loop score {float(agent.get('loop_score') or 0):.2f}, "
            f"same prompt repeated {int(agent.get('exact_repeats') or 0)}×, "
            f"memory {float(agent.get('memory_pct') or 0):.0f}%.")
    if verdicts:
        verdict = verdicts[0]
        text += (f" Latest verdict ({verdict.get('source')}): {verdict.get('action')} at "
                 f"{float(verdict.get('confidence') or 0):.0%}, {verdict.get('pattern')}: "
                 f"{verdict.get('reason')}")
        if verdict.get("suggested_fix"):
            text += f" Suggested fix: {verdict['suggested_fix']}"
    return text


@mcp.tool(annotations=SAFE)
def get_memory(agent_id: str) -> dict:
    """Read an agent's external memory (latest version)."""
    return client.get(f"{_agent_path(agent_id)}/memory")


@mcp.tool(annotations=SAFE)
def list_pending_tool_calls() -> list[dict]:
    """Tool calls waiting for a human decision (e.g. large refunds)."""
    return client.get("/v1/tool-calls?status=pending")["items"]


@mcp.tool(annotations=SAFE)
def get_roi_report() -> dict:
    """Money spent, money saved by each intervention, and the formula used."""
    return client.get("/v1/roi")


@mcp.tool(annotations=SAFE)
def get_policy() -> dict:
    """The policy in force: budgets, what a tripped breaker does, and the tool-call rules."""
    return client.get("/v1/policy")


@mcp.tool(annotations=SAFE)
def validate_policy(yaml: str) -> dict:
    """
    Check a policy file's text without changing anything.

    Returns the errors with the exact path of what is wrong ("tools[2].when.op: must be one of
    gt, gte, lt, lte, eq, ne, contains"), so the file can be fixed before it is deployed.
    """
    return client.post("/v1/policy/validate", {"yaml": check_yaml(yaml)})


@mcp.tool(annotations=SAFE)
def list_heal_proposals(status: str = "pending") -> list[dict]:
    """Heal proposals waiting for a decision (the judge's proposed patches for sick agents)."""
    status = check_choice(status, ("pending", "applied", "rejected", "expired"), "status")
    return client.get(f"/v1/heal-proposals?status={status}")["items"]


# ── write tools ──────────────────────────────────────────────────────────────
@mcp.tool(annotations=DESTRUCTIVE)
def pause_agent(agent_id: str, reason: str) -> dict:
    """Pause (quarantine) an agent. Its container is frozen with state intact; resume_agent undoes it."""
    return _command(agent_id, "PAUSE", reason)


@mcp.tool(annotations=DESTRUCTIVE)
def resume_agent(agent_id: str, reason: str) -> dict:
    """Resume a paused agent. It runs on probation (stricter limits) for a while."""
    return _command(agent_id, "RESUME", reason)


@mcp.tool(annotations=DESTRUCTIVE)
def kill_agent(agent_id: str, reason: str) -> dict:
    """Kill an agent's container immediately. Prefer pause_agent unless it is dangerous."""
    return _command(agent_id, "KILL", reason)


@mcp.tool(annotations=DESTRUCTIVE)
def set_budget(agent_id: str, budget_usd: float, reason: str = "") -> dict:
    """Set an agent's session budget in USD. Exceeding it trips the breaker."""
    amount = check_number(budget_usd, "budget_usd", minimum=0.01, maximum=10_000)
    return _command(agent_id, "SET_BUDGET", reason or f"budget set to ${amount}",
                    {"budget_usd": amount})


@mcp.tool(annotations=DESTRUCTIVE)
def edit_memory(agent_id: str, content: dict, reason: str) -> dict:
    """Replace an agent's memory with `content` (a JSON object). The agent reads it on its next step."""
    _guard_write()
    _guard_rate_limit()
    body = {"content": check_content(content), "edited_by": "mcp",
            "reason": check_reason(reason), "base_version": None}
    return client.put(f"{_agent_path(agent_id)}/memory", body)


@mcp.tool(annotations=DESTRUCTIVE)
def decide_tool_call(call_id: int, decision: str, reason: str, final_args: Optional[dict] = None) -> dict:
    """Decide a pending tool call: decision = allow | deny | rewrite (rewrite needs final_args)."""
    _guard_write()
    _guard_rate_limit()
    choice = check_choice(decision, ("allow", "deny", "rewrite"), "decision")
    body = {"decision": choice, "final_args": final_args, "decided_by": "mcp",
            "reason": check_reason(reason)}
    if choice == "rewrite" and not isinstance(final_args, dict):
        raise ToolError("rewrite needs final_args (the new arguments)", "final_args")
    return client.post(f"/v1/tool-calls/{check_positive_id(call_id, 'call_id')}/decision", body)


@mcp.tool(annotations=DESTRUCTIVE)
def decide_heal(proposal_id: int, decision: str, reason: str) -> dict:
    """
    Decide a heal proposal: decision = apply | reject.

    `apply` writes the judge's patch into the agent's memory (the belief that is keeping it
    looping, or a tool policy). `reject` leaves the agent paused for a human to look at.
    """
    _guard_write()
    _guard_rate_limit()
    choice = check_choice(decision, ("apply", "reject"), "decision")
    body = {"decision": choice, "reason": check_reason(reason), "requested_by": "mcp"}
    return client.post(f"/v1/heal-proposals/{check_positive_id(proposal_id, 'proposal_id')}/decision",
                       body)


# ── resources ────────────────────────────────────────────────────────────────
@mcp.resource("cloudsentinel://fleet", mime_type="application/json",
              description="The whole fleet as JSON: every agent with its state, spend and loop score.")
def fleet_resource() -> str:
    return json.dumps(client.get("/v1/fleet"), default=str, indent=2)


@mcp.resource("cloudsentinel://agents/{agent_id}", mime_type="application/json",
              description="One agent in full: metrics, the last judge verdicts and its memory.")
def agent_resource(agent_id: str) -> str:
    data = client.get(_agent_path(agent_id))
    return json.dumps(data, default=str, indent=2)


# ── prompts ──────────────────────────────────────────────────────────────────
@mcp.prompt(name="triage_fleet", description="A checklist for triaging the fleet: what to look at first.")
def triage_fleet() -> str:
    return (
        "Triage the CloudSentinel fleet.\n\n"
        "1. Call list_agents and sort by spend rate ($/min), then by loop score.\n"
        "2. For the two worst agents, call explain_agent to read why the brain acted.\n"
        "3. For any agent that is paused with a loop verdict, look at its memory with "
        "get_memory. If the memory holds a wrong belief (an API error that says 'retry until "
        "success'), fix it with edit_memory — then resume_agent.\n"
        "4. For a pending tool call that moves money, use decide_tool_call to deny anything "
        "unexplained.\n"
        "5. Prefer pause over kill: a paused agent keeps its state and can be healed.\n\n"
        "Give a short reason for every action — it is written to the audit log."
    )


# ── entry point ──────────────────────────────────────────────────────────────
def _check_http_bind(cfg: McpSettings) -> None:
    """
    --http on a non-localhost bind is a remote-control surface. It needs a token.

    Without one, the server refuses to start rather than exposing the fleet to the network.
    """
    if cfg.is_local_bind:
        return
    if not cfg.api_token:
        raise SystemExit(
            f"refusing to serve MCP over HTTP on {cfg.http_host}: that is reachable from "
            f"other machines.\n"
            f"Set CS_API_TOKEN to a secret value, or bind a local address with "
            f"--host 127.0.0.1.\n"
            f"(the API then requires \"Authorization: Bearer <token>\" on every request)")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cloudsentinel-mcp",
        description="CloudSentinel MCP server — operate the AI-agent circuit breaker from Claude.")
    parser.add_argument("--http", action="store_true",
                        help="Streamable HTTP instead of stdio (needs a token on a public bind)")
    parser.add_argument("--host", default=settings.http_host,
                        help=f"the address to bind in --http mode (default {settings.http_host})")
    parser.add_argument("--port", type=int, default=settings.http_port,
                        help=f"the port to bind in --http mode (default {settings.http_port})")
    parser.add_argument("--api-url", default=settings.api_url,
                        help=f"the CloudSentinel API to talk to (default {settings.api_url})")
    parser.add_argument("--readonly", action="store_true",
                        help="expose only the tools that change nothing")
    parser.add_argument("--rate-limit", type=int, default=settings.rate_limit_per_min,
                        help=f"destructive calls per minute (default {settings.rate_limit_per_min})")
    args = parser.parse_args(argv)

    # The CLI overrides win over the environment.
    if args.readonly:
        settings.readonly = True
    if args.api_url:
        settings.api_url = args.api_url.rstrip("/")
    if args.rate_limit >= 0:
        settings.rate_limit_per_min = args.rate_limit
    settings.http_host = args.host
    settings.http_port = args.port

    client.base_url = settings.api_url
    client.token = settings.api_token
    limiter.limit = settings.rate_limit_per_min
    limiter.reset()

    if args.http:
        _check_http_bind(settings)
        mcp.run("streamable-http", host=settings.http_host, port=settings.http_port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main(sys.argv[1:])
