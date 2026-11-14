# cloudsentinel SDK

Telemetry and control for AI agents. Spans go out over OpenTelemetry (OTLP/HTTP). The tool gate and the
external memory use the CloudSentinel API.

## Quick start

```bash
pip install -e telemetry/sdk
```

```python
import cloudsentinel as cs

cs.init(agent_id="beta")
with cs.task("track order 4471") as t:
    cs.tool("search_kb", {"q": "order 4471"}, fn=lambda q: "ok")
    t.success()
```

Nothing needs to be running for this to work: if CloudSentinel is down, the tool simply runs
(see "When CloudSentinel is down").

## Public functions

### `cs.init(agent_id=None, runtime="local", api_url=None, otlp_endpoint=None)`
Call once at start-up. Every argument falls back to an environment variable (see Settings).
```python
cs.init(agent_id="beta", runtime="docker")
```

### `cs.task(description="", task_id=None)`
Context manager, one `invoke_agent` span. Mark the result with `t.success()` or `t.failure("reason")`.
```python
with cs.task("refund order 4471") as t:
    ...
    t.success()          # or t.failure("orders_api 500")
```

### `cs.llm_call(model, provider="anthropic", prompt="")`
Context manager, one `chat` span. Call `record()` with the token counts so the cost can be priced.
```python
with cs.llm_call(model="claude-haiku-5-5", provider="anthropic", prompt=prompt) as call:
    answer = my_llm(prompt)
    call.record(input_tokens=1000, output_tokens=200)
```

### `cs.tool(name, args, fn, value_usd=None, fail_closed=False)`
Asks the tool gate first, then runs `fn(**args)` inside an `execute_tool` span.
allow runs `fn(**args)`, rewrite runs `fn(**final_args)`, deny or timeout raises `cs.ToolDenied`.
```python
try:
    cs.tool("issue_refund", {"order_id": 4471, "amount": 50000}, fn=issue_refund,
            value_usd=410.0, fail_closed=True)
except cs.ToolDenied:
    print("refund blocked")
```

### `cs.gate(name, args, value_usd=None, fail_closed=False)`
Asks the gate without running anything. Returns `(decision, final_args)`. Blocks while a human decides.
```python
decision, final_args = cs.gate("issue_refund", {"amount": 50000}, value_usd=410.0)
if decision in ("deny", "timeout"):
    raise cs.ToolDenied("not allowed")
```

### `cs.node(name, step=None, framework="custom")`
Context manager, one `graph_node` span (the framework adapters do this for you).
```python
with cs.node("lookup_order", step=1) as n:
    n.changed({"order_status": "refunded"})
```

### `cs.wait_if_paused(poll_seconds=1.0, max_wait=None)`
For agents without a container: blocks while CloudSentinel has the agent paused, raises
`cs.AgentKilled` if it was killed. Returns at once if the API is unreachable.
```python
while work_left():
    cs.wait_if_paused()
    do_one_step()
```

### `cs.memory.get()` and `cs.memory.set(content, reason="")`
External memory kept by CloudSentinel, so a human can fix it while the agent is paused.
`get()` returns the latest dict (`{}` if none). `set()` returns `False` if a human changed the memory
in the meantime: call `get()` again.
```python
mem = cs.memory.get()
if not cs.memory.set({**mem, "last_order": 4471}, "agent saved progress"):
    mem = cs.memory.get()
```

### `cs.flush()`
Sends the spans that are still waiting. Call it before a short script exits.
```python
cs.flush()
```

Also exported: `cs.start_span(name, operation, attributes=None, parent=None)` and `cs.end_span(span, error=None)`
for callback-style framework hooks, `cs.preview_delta(update)`, and the exceptions `cs.ToolDenied` and
`cs.AgentKilled`.

## Adapters

- LangGraph: see `telemetry/examples/langgraph_refund_agent.py`
- CrewAI: see `telemetry/examples/crewai_support_crew.py`
- OpenAI Agents: not available yet.

The adapter code is in `telemetry/sdk/cloudsentinel/adapters/`.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CS_AGENT_ID` (or `AGENT_NAME`) | `agent` | name of this agent |
| `CS_API_URL` | `http://127.0.0.1:8000` | CloudSentinel API (tool gate, memory) |
| `CS_API_TOKEN` | empty | sent as the `X-CS-Token` header |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://127.0.0.1:4318` | collector that receives the spans |
| `CS_CAPTURE_PROMPTS` | `true` | set to `false` to stop sending prompt previews |
| `TOOL_APPROVAL_TIMEOUT_SECONDS` | `120` | how long a tool call waits for a human |

The defaults use `127.0.0.1` and not `localhost` on purpose: on Windows `localhost` tries IPv6 first
and every call waits about 2 seconds.

## When CloudSentinel is down

- Telemetry is best-effort. If the OpenTelemetry packages are missing, telemetry does nothing.
- `cs.tool(...)` **fails open**: if the API cannot be reached, the tool runs. Pass `fail_closed=True`
  for tools that move money: then an unreachable gate counts as a denial.
- `cs.wait_if_paused()` returns at once if the API cannot be reached.
- When the API is reachable, the gate denies every tool call from an agent that the breaker has paused or killed.
