# 🛡️ CloudSentinel

**The circuit breaker and control tower for AI agent fleets.**
CloudSentinel watches every agent through OpenTelemetry. When an agent loops, overspends or tries a
dangerous tool call, it **pauses, heals or kills** it within seconds, from *outside* the agent so a
broken agent can't bypass it. Then it shows you how much money that saved.

> AgentOps tools are the black-box recorder. CloudSentinel is the circuit breaker.

Built for the **International AI Builders Congress 2026 · InfraSphere AI · AgentOps** challenge.

```
 agents (any framework) ──OTel GenAI spans──▶ collector :4318 ──▶ store ◀── brain: rules → semantic loop → Claude judge
        ▲   │ tool gate · memory                                                    │ breaker FSM · policy-as-code
        │   └──────────────▶ C2 API :8000 ◀── dashboard :8501 · MCP server (Claude) │
        └──────────── pause / resume / kill (Docker · K8s executor) ◀───────────────┘
```

| What | How |
|---|---|
| **Observe** | `cloudsentinel` SDK (3 lines) emits OTel GenAI spans (`invoke_agent`, `chat`, `execute_tool`). Any OTel-instrumented agent works |
| **Decide** | Hard limits (budget, tokens/min, calls/s, memory) → semantic-loop and tool-cycle detection (no LLM) → **Claude judge** for gray zones, with a fail-safe fallback |
| **Act** | A real breaker state machine: healthy → suspicious → **paused** → probation → healthy (or killed). `docker pause` keeps state for forensics |
| **Command & Control** | REST API + **MCP server**: pause/resume/kill, **edit agent memory**, **approve/deny/rewrite tool calls**, budgets. Every action is audited |
| **Prove** | ROI engine: **$ saved per intervention**, plus a runaway-agent benchmark (`python -m eval.harness`) |

## Quick start (no Docker, no API key, works offline)

```bash
git clone https://github.com/abdullahalyf/Cloud-Sentinel.git && cd Cloud-Sentinel
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # Windows: copy .env.example .env
python scripts/check_setup.py
python -m brain --fake              # terminal 1: brain + C2 API + 4 simulated agents (beta goes rogue after 20 s)
streamlit run dashboard/app.py      # terminal 2: http://localhost:8501
```
About 20 s later, **beta** starts a paraphrase loop and gets **paused**. Open the memory editor, fix
`order_4471`, press **Resume**, and beta goes to probation and then back to healthy. Press *Simulate incident*
on **gamma** (token bomb → killed by hard rules) and **delta** (a 50,000 BDT refund held for approval).

Add `ANTHROPIC_API_KEY` to `.env` to switch the judge from the fallback rules to Claude.

## Full stack in Docker

```bash
docker compose up -d --build                         # collector, brain, dashboard + 4 agent containers
python scripts/demo.py rogue beta paraphrase_loop    # or: token_bomb gamma · bad_tool_call delta
python scripts/demo.py fix beta && python scripts/demo.py resume beta
python scripts/demo.py reset
```

## Operate it from Claude (MCP)
```json
{"mcpServers": {"cloudsentinel": {"command": "python", "args": ["-m", "brain.mcp_server"],
  "cwd": "/path/to/Cloud-Sentinel", "env": {"CS_API_URL": "http://localhost:8000"}}}}
```
Then ask: *"Which agent is costing us the most? Pause it and explain why."*

## Instrument your own agent
```python
import cloudsentinel as cs                     # pip install -e telemetry/sdk
cs.init(agent_id="my-agent")
with cs.task("answer ticket") as t:
    with cs.llm_call(model="claude-haiku-5-5", prompt=prompt) as call:
        resp = client.messages.create(...)
        call.record(resp.usage.input_tokens, resp.usage.output_tokens)
    cs.tool("issue_refund", {"amount": 500}, fn=issue_refund, value_usd=4.1, fail_closed=True)
    t.success()
```

### LangGraph and CrewAI: one line each
```python
from cloudsentinel.adapters.langgraph import CloudSentinelCallback, guard     # pip install -e "telemetry/sdk[langgraph]"
app.invoke(state, config={"callbacks": [CloudSentinelCallback()]})            # task, node + state delta, chat, tool spans
tools = [guard(issue_refund, value_usd=lambda a: a["amount"] / 122, fail_closed=True)]   # tool gate

from cloudsentinel.adapters.crewai import instrument                         # pip install -e "telemetry/sdk[crewai]"
instrument(value_usd={"issue_refund": lambda a: a["amount"] / 122}, fail_closed=("issue_refund",))
```
Demo agents (run offline): `telemetry/examples/langgraph_refund_agent.py --rogue-after 20` (a recursive
`lookup_order ↔ retry` loop that CloudSentinel pauses between nodes, then heals with a memory edit) and
`telemetry/examples/crewai_support_crew.py` (a 50,000 BDT refund held by the tool gate). Their live node flow
is served by `GET /v1/agents/{id}/nodes`. CrewAI pins `mcp<2`, so install it in the agent's own venv, not next to the brain.

### Also send everything to Arize Phoenix
`CS_EXPORT_PHOENIX=true python -m telemetry.collector` (or `CS_EXPORT_PHOENIX=true docker compose --profile phoenix up -d`).
The collector forwards every batch to Phoenix (`PHOENIX_COLLECTOR_ENDPOINT`, default `http://localhost:6006`) with
OpenInference attributes added, so Phoenix shows the traces, and CloudSentinel does the stopping.

## Repo map
| Folder | What | Owner |
|---|---|---|
| `brain/` | engine, detectors, breaker, policy, Claude judge, C2 API, MCP server | Alif |
| `telemetry/` | SDK, OTLP collector, simulators, DB schema | Fojle |
| `infra/` | Docker/K8s executors, Dockerfiles, CI | Taseen |
| `dashboard/` | Streamlit control tower | Tamjid |
| `eval/` | ROI engine, benchmark, QA, pitch | Orin |
| `shared/` | **contracts**, config, store, pricing, mocks | Alif + Taseen |

Docs: [Decision](docs/DECISION.md) · [Architecture](docs/ARCHITECTURE.md) · [Contracts](docs/CONTRACTS.md) ·
[Plan](docs/PLAN.md) · [Tasks](docs/tasks/) · [Research](docs/research/) · [Branching](docs/BRANCHING.md) ·
[বাংলা সারাংশ](docs/SUMMARY_BN.md) · AI-tool rules: [AGENTS.md](AGENTS.md), [.agents/rules](.agents/rules/cloudsentinel.md)

## Tests
```bash
python -m pytest -q        # unit + end-to-end (fake fleet on a virtual clock) + API/mock parity
python -m eval.harness     # runaway-agent benchmark
```
