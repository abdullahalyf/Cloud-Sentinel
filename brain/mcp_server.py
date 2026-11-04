"""
CloudSentinel MCP server (CONTRACTS §7): lets Claude Desktop / Claude Code operate the agent fleet.

Every tool calls the C2 REST API (CS_API_URL), so it also works against the mock API.

    python -m brain.mcp_server            # stdio (for Claude Desktop / Claude Code)
    python -m brain.mcp_server --http     # Streamable HTTP on :8765/mcp

Claude Desktop config (claude_desktop_config.json):
    {"mcpServers": {"cloudsentinel": {"command": "python", "args": ["-m", "brain.mcp_server"],
      "cwd": "<path to repo>", "env": {"CS_API_URL": "http://localhost:8000"}}}}
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from shared.config import settings

SAFE = ToolAnnotations(read_only_hint=True, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

mcp = MCPServer("cloudsentinel", instructions=(
    "CloudSentinel is a circuit breaker for AI agents. Use list_agents first. Prefer pause_agent over "
    "kill_agent: a paused agent keeps its state and can be healed with edit_memory and resumed. "
    "Always give a short reason; it is written to the audit log."))


def _api(method: str, path: str, body: Optional[dict] = None) -> Any:
    headers = {"X-CS-Token": settings.api_token} if settings.api_token else {}
    with httpx.Client(base_url=settings.api_url, timeout=10.0, headers=headers) as client:
        r = client.request(method, path, json=body)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(f"CloudSentinel API {r.status_code}: {detail}")
    return r.json()


def _command(agent_id: str, command: str, reason: str, params: Optional[dict] = None) -> dict:
    res = _api("POST", f"/v1/agents/{agent_id}/commands",
               {"command": command, "params": params or {}, "requested_by": "mcp", "reason": reason})
    return {**res, "note": "The engine executes commands within ~1 second. Check with get_agent."}


@mcp.tool(annotations=SAFE)
def list_agents() -> list[dict]:
    """List every agent with its breaker state, spend rate ($/min), spend vs budget and loop score."""
    return [{k: a[k] for k in ("agent_id", "state", "usd_per_min", "spend_usd", "budget_usd", "tokens_per_min",
                               "loop_score", "exact_repeats", "memory_pct")}
            for a in _api("GET", "/v1/fleet")["agents"]]


@mcp.tool(annotations=SAFE)
def get_agent(agent_id: str) -> dict:
    """Full details of one agent: metrics, last judge verdicts and current memory."""
    data = _api("GET", f"/v1/agents/{agent_id}")
    return {"agent": data["agent"], "verdicts": data["verdicts"][:3], "memory": data["memory"]}


@mcp.tool(annotations=SAFE)
def explain_agent(agent_id: str) -> str:
    """Plain-English explanation of why an agent is in its current state."""
    data = _api("GET", f"/v1/agents/{agent_id}")
    a, verdicts = data["agent"], data["verdicts"]
    text = (f"{agent_id} is {a['state'].upper()}. Spending ${a['usd_per_min']:.4f}/min, "
            f"${a['spend_usd']:.3f} of ${a['budget_usd']:.2f} budget. Loop score {a['loop_score']:.2f}, "
            f"same prompt repeated {a['exact_repeats']}×, memory {a['memory_pct']:.0f}%.")
    if verdicts:
        v = verdicts[0]
        text += f" Latest verdict ({v['source']}): {v['action']} at {v['confidence']:.0%}, {v['pattern']}: {v['reason']}"
        if v.get("suggested_fix"):
            text += f" Suggested fix: {v['suggested_fix']}"
    return text


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
    return _command(agent_id, "SET_BUDGET", reason or f"budget set to ${budget_usd}", {"budget_usd": budget_usd})


@mcp.tool(annotations=SAFE)
def get_memory(agent_id: str) -> dict:
    """Read an agent's external memory (latest version)."""
    return _api("GET", f"/v1/agents/{agent_id}/memory")


@mcp.tool(annotations=DESTRUCTIVE)
def edit_memory(agent_id: str, content: dict, reason: str) -> dict:
    """Replace an agent's memory with `content` (a JSON object). The agent reads it on its next step."""
    return _api("PUT", f"/v1/agents/{agent_id}/memory",
                {"content": content, "edited_by": "mcp", "reason": reason, "base_version": None})


@mcp.tool(annotations=SAFE)
def list_pending_tool_calls() -> list[dict]:
    """Tool calls waiting for a human decision (e.g. large refunds)."""
    return _api("GET", "/v1/tool-calls?status=pending")["items"]


@mcp.tool(annotations=DESTRUCTIVE)
def decide_tool_call(call_id: int, decision: str, reason: str, final_args: Optional[dict] = None) -> dict:
    """Decide a pending tool call: decision = allow | deny | rewrite (rewrite needs final_args)."""
    return _api("POST", f"/v1/tool-calls/{call_id}/decision",
                {"decision": decision, "final_args": final_args, "decided_by": "mcp", "reason": reason})


@mcp.tool(annotations=SAFE)
def get_roi_report() -> dict:
    """Money spent, money saved by each intervention, and the formula used."""
    return _api("GET", "/v1/roi")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m brain.mcp_server")
    p.add_argument("--http", action="store_true", help="Streamable HTTP on :8765/mcp instead of stdio")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    if args.http:
        mcp.run("streamable-http", host="0.0.0.0", port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
