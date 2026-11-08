# cloudsentinel-mcp

The CloudSentinel MCP server as a standalone package. It lets Claude Desktop, Claude Code
or Codex operate your AI-agent fleet: see which agent is burning money, pause the one that
is looping, fix its memory, and resume it.

It talks to the CloudSentinel C2 API over HTTP, so it works against a real deployment and
against the mock API in the repo's test suite.

## Install

```bash
pip install ./brain/mcp_pkg        # from a clone of Cloud-Sentinel
cloudsentinel-mcp --help
```

Runtime dependencies are only `httpx` and `mcp`. The package does not import the
CloudSentinel repo.

## Configure

| variable | default | meaning |
|---|---|---|
| `CS_API_URL` | `http://localhost:8000` | the CloudSentinel API to talk to |
| `CS_API_TOKEN` | *(empty)* | sent as `X-CS-Token` and `Authorization: Bearer`; required for a public HTTP bind |
| `CS_MCP_READONLY` | `false` | expose only the tools that change nothing |
| `CS_MCP_RATE_LIMIT` | `30` | destructive calls per minute, per session |
| `CS_MCP_HTTP_HOST` | `127.0.0.1` | the address `--http` binds |
| `CS_MCP_HTTP_PORT` | `8765` | the port `--http` binds |

## Run

```bash
cloudsentinel-mcp                                  # stdio
cloudsentinel-mcp --http --port 8765               # Streamable HTTP
cloudsentinel-mcp --readonly                       # no write tools
cloudsentinel-mcp --api-url http://cs.internal:8000
```

`--http` on a **non-localhost** bind refuses to start unless `CS_API_TOKEN` is set. A
public bind without a token is a remote-control surface for your fleet, so the server
shuts down instead of serving it. The API then requires the token on every request.

## Tools

**Read** — `list_agents`, `get_agent`, `explain_agent`, `get_memory`,
`list_pending_tool_calls`, `get_roi_report`, `get_policy`, `validate_policy`,
`list_heal_proposals`.

**Write** — `pause_agent`, `resume_agent`, `kill_agent`, `set_budget`, `edit_memory`,
`decide_tool_call`, `decide_heal`.

Every write tool requires a `reason`; it is written to the audit log.

## Resources and prompts

- `cloudsentinel://fleet` — the whole fleet as JSON
- `cloudsentinel://agents/{agent_id}` — one agent in full
- the `triage_fleet` prompt — a checklist for working through the fleet

## Claude Desktop / Claude Code config

```json
{
  "mcpServers": {
    "cloudsentinel": {
      "command": "cloudsentinel-mcp",
      "env": { "CS_API_URL": "http://localhost:8000" }
    }
  }
}
```

## Safety

- every argument is validated before it reaches the API — a bad id or a missing reason
  comes back as a readable message, not a stack trace
- destructive calls are rate limited per session; reads are never throttled
- `--readonly` hides every write tool

## License

MIT
