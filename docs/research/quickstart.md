# Quickstart — five lines, from a clean virtualenv

This is the whole install story. It is deliberately short: a stranger should be
able to read it once and type it.

## The SDK — one agent, guarded

```bash
python -m venv .venv && .venv/bin/pip install ./telemetry/sdk
```

```python
import cloudsentinel as cs
cs.init(agent_id="refund-bot")
with cs.task("refund order 4471") as t:
    with cs.llm_call(model="claude-haiku-4-5", provider="anthropic") as call:
        call.record(input_tokens=120, output_tokens=340)
    t.success()
```

`cs.tool("issue_refund", {...}, fn=issue_refund)` asks the control tower before
the tool runs; `cs.gate(...)` is the same call without the wrapper. Neither
needs the CloudSentinel repo — only the SDK.

## The MCP server — the fleet, from Claude

```bash
python -m venv .venv && .venv/bin/pip install ./brain/mcp_pkg
```

```bash
cloudsentinel-mcp --api-url http://localhost:8000
```

It speaks MCP over stdio, so point an MCP client at the command. It exposes
**17 tools**: `list_agents`, `get_agent`, `explain_agent`, `get_roi_report`,
`get_policy`, `pause_agent`, `kill_agent`, `set_budget`, `decide_tool_call`,
and the rest.

To see the fleet without an MCP client, the same API answers it directly:

```bash
curl -s http://localhost:8000/v1/fleet | python -m json.tool
```

## See it work, end to end

```bash
docker compose up -d && python -m brain --fake
```

Four simulated agents. The API is on `localhost:8000`; `beta` starts misbehaving
after 20 seconds and the breaker opens it.

## What was checked

`brain/tests/test_packaging.py` builds a **real virtualenv**, really installs
both packages, and runs the code **inside that venv** with the repo *not* on
the path. It is marked `live`, so it is skipped when there is no network:

```bash
python -m pytest brain/tests/test_packaging.py -q -m live
```

Five checks, all of which pass:

| What is checked | How |
| --- | --- |
| `pip install ./telemetry/sdk` works | real venv, real install, then `import cloudsentinel` |
| the SDK has the surface an agent calls | `init`, `llm_call`, `tool`, `gate`, `task`, `node`, `memory`, `wait_if_paused` — all present in the *installed* package |
| `pip install ./brain/mcp_pkg` works | real venv, real install, then `cloudsentinel-mcp --help` |
| the installed server answers | driven over **real MCP stdio**, and it lists its **17 tools** |
| the whole story end to end | the installed server talks to a running `python -m brain --fake` and returns a **real fleet** |

The last one is the one that matters. Everything before it could pass with a
server that answers nothing at all.

## The versions

| Package | Version | Installs from |
| --- | --- | --- |
| `cloudsentinel` | 0.3.0 | `./telemetry/sdk` |
| `cloudsentinel-mcp` | 0.7.0 | `./brain/mcp_pkg` |
