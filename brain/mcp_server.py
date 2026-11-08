"""
CloudSentinel MCP server (CONTRACTS §7): lets Claude Desktop / Claude Code operate the agent fleet.

Every tool calls the C2 REST API (CS_API_URL), so it also works against the mock API.

    python -m brain.mcp_server            # stdio (for Claude Desktop / Claude Code)
    python -m brain.mcp_server --http     # Streamable HTTP on :8765/mcp

Claude Desktop config (claude_desktop_config.json):
    {"mcpServers": {"cloudsentinel": {"command": "python", "args": ["-m", "brain.mcp_server"],
      "cwd": "<path to repo>", "env": {"CS_API_URL": "http://localhost:8000"}}}

**This module is a thin wrapper.** The implementation lives in
`brain/mcp_pkg/cloudsentinel_mcp/` — the same code the `cloudsentinel-mcp` package ships
(A7). It is re-exported here so `python -m brain.mcp_server` and the installed command
behave identically, and so there is only one server to keep hardened.

See brain/MCP.md for the tools, the config snippets and the safety rules.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The packaged server is a sibling directory, not an installed package. Adding it to the
# path keeps `python -m brain.mcp_server` working from a checkout with nothing installed.
_PKG = Path(__file__).resolve().parent / "mcp_pkg"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from cloudsentinel_mcp.server import (  # noqa: E402  (the path insert has to come first)
    DESTRUCTIVE,
    DESTRUCTIVE_TOOLS,
    READ_ONLY_TOOLS,
    SAFE,
    client,
    limiter,
    mcp,
)
from cloudsentinel_mcp.server import (  # noqa: E402  (the tool functions themselves)
    decide_heal,
    decide_tool_call,
    edit_memory,
    explain_agent,
    get_agent,
    get_memory,
    get_policy,
    get_roi_report,
    get_tool_risk,
    kill_agent,
    list_agents,
    list_heal_proposals,
    list_pending_tool_calls,
    pause_agent,
    resume_agent,
    set_budget,
    validate_policy,
)
from cloudsentinel_mcp.hardening import ToolError  # noqa: E402

# Re-exported so the repo's tests can point the server at the mock API by patching
# `brain.mcp_server.httpx.Client` — the same seam the server itself uses.
import httpx  # noqa: E402,F401

__all__ = ["mcp", "main", "SAFE", "DESTRUCTIVE", "DESTRUCTIVE_TOOLS", "READ_ONLY_TOOLS",
           "client", "limiter", "ToolError", "httpx",
           "list_agents", "get_agent", "explain_agent", "get_memory", "list_pending_tool_calls",
           "get_roi_report", "get_policy", "validate_policy", "list_heal_proposals", "get_tool_risk",
           "pause_agent", "resume_agent", "kill_agent", "set_budget", "edit_memory",
           "decide_tool_call", "decide_heal"]


def main(argv=None) -> None:
    """Run the server. See brain/MCP.md."""
    from cloudsentinel_mcp.server import main as _main

    _main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
