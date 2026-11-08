# The CloudSentinel MCP server

CloudSentinel is a circuit breaker for AI agents. The MCP server is how Claude Desktop,
Claude Code or Codex **operate** the fleet: see which agent is burning money, pause the one
that is looping, fix its memory, resume it.

There is one implementation. It lives in `brain/mcp_pkg/cloudsentinel_mcp/` and is packaged
as `cloudsentinel-mcp`. The in-repo `brain/mcp_server.py` is a thin wrapper, so
`python -m brain.mcp_server` and the installed command behave identically.

## Install

```bash
pip install ./brain/mcp_pkg
cloudsentinel-mcp --help
```

The package needs only `httpx` and `mcp` at runtime — it does not import the CloudSentinel
repo, so it can be installed on its own (on a laptop, in Claude Desktop, in a container
that has never seen this codebase).

## Configure

| variable | default | meaning |
|---|---|---|
| `CS_API_URL` | `http://localhost:8000` | the CloudSentinel API to talk to |
| `CS_API_TOKEN` | *(empty)* | sent as `X-CS-Token` and `Authorization: Bearer` |
| `CS_MCP_READONLY` | `false` | expose only the tools that change nothing |
| `CS_MCP_RATE_LIMIT` | `30` | destructive calls per minute, per session |
| `CS_MCP_HTTP_HOST` | `127.0.0.1` | the address `--http` binds |
| `CS_MCP_HTTP_PORT` | `8765` | the port `--http` binds |

## Run

```bash
cloudsentinel-mcp                                    # stdio
python -m brain.mcp_server                           # the same thing, from the repo
cloudsentinel-mcp --http --port 8765                 # Streamable HTTP
cloudsentinel-mcp --readonly                         # no write tools
```

### The HTTP bind and the token

`--http` on a **non-localhost** bind refuses to start unless `CS_API_TOKEN` is set:

```
refusing to serve MCP over HTTP on 0.0.0.0: that is reachable from other machines.
Set CS_API_TOKEN to a secret value, or bind a local address with --host 127.0.0.1.
```

A public bind without a token is a remote-control surface for your fleet — anyone who can
reach the port can pause and kill agents. The server shuts down instead of serving it. With
a token set, the API requires `Authorization: Bearer <token>` on every request.

## Config snippets

### Claude Desktop

`claude_desktop_config.json`:

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

### Claude Code

```bash
claude mcp add cloudsentinel -- cloudsentinel-mcp
# or, with the repo checkout instead of the installed package:
claude mcp add cloudsentinel -- python -m brain.mcp_server
```

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.cloudsentinel]
command = "cloudsentinel-mcp"
env = { CS_API_URL = "http://localhost:8000" }
```

## Tools

**Read** (nothing changes):

| tool | what it does |
|---|---|
| `list_agents` | every agent with its state, spend rate, spend vs budget, loop score |
| `get_agent` | one agent in full: metrics, the last verdicts, its memory |
| `explain_agent` | plain-English: why is this agent in this state |
| `get_memory` | an agent's memory (the latest version) |
| `list_pending_tool_calls` | the calls waiting for a human (a big refund, say) |
| `get_roi_report` | money spent, money saved, and the formula |
| `get_policy` | the policy in force |
| `validate_policy` | check a policy file's text without changing anything |
| `list_heal_proposals` | the judge's proposed patches, waiting for a decision |

**Write** (they change the fleet):

| tool | what it does |
|---|---|
| `pause_agent` | freeze an agent, state intact — the one to prefer |
| `resume_agent` | resume it on probation |
| `kill_agent` | kill its container — only when pause is not enough |
| `set_budget` | change its session budget |
| `edit_memory` | replace its memory |
| `decide_tool_call` | allow / deny / rewrite a held tool call |
| `decide_heal` | apply or reject a heal proposal |

Every write tool requires a `reason`. It is written to the audit log — that is the whole
point of the audit trail, so do not leave it empty.

## Resources and prompts

- `cloudsentinel://fleet` — the whole fleet as JSON
- `cloudsentinel://agents/{agent_id}` — one agent in full
- the `triage_fleet` prompt — a checklist for working through the fleet

## Safety

- **Input validation.** Every argument is checked before it reaches the API: the agent id
  must be a short safe identifier (it goes into a URL), the reason must be present and
  under 500 characters, the decision must be one of the allowed values, the budget must be
  a finite number in range. A bad argument comes back as a readable message — *"reason is
  required — it is written to the audit log"* — never a stack trace.
- **Rate limit.** Destructive calls are capped per session (30/min by default). Reads are
  never throttled: a dashboard should not be rate limited.
- **Read-only mode.** `CS_MCP_READONLY=true` (or `--readonly`) hides every write tool, so a
  read-only client cannot pause anything even by accident.
- **Annotated tools.** Every tool declares `readOnlyHint` and `destructiveHint`, and a test
  checks that the annotation agrees with what the tool actually does. A tool in neither set
  fails the test — an un-audited tool cannot ship.

## Tests

```bash
python -m pytest -q brain/tests/test_mcp_hardening.py   # the A7 acceptance tests
python -m pytest -q brain/tests/test_mcp.py             # the tools against the mock API
```

The acceptance tests build the wheel with `pip wheel`, check that the package does not
import `shared/`, drive an in-process stdio client against the mock API, and cover the
token requirement, read-only mode and the rate limit.
