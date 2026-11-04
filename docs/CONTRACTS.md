# CONTRACTS v2 — frozen on Day 1 (2026-11-05)

These are the **only** ways the five layers talk to each other. The code version of this file is
`shared/contracts.py` (dataclasses + constants) and `telemetry/db/schema.sql` (tables).
If the code and this doc disagree, **the code wins** — and open an issue.

**Change process:** need a new field? STOP. Write it in your PR description / tell Alif + Taseen.
Only Alif or Taseen edit `shared/`. Adding an *optional* field with a default is a minor change
(1 approval); renaming or removing anything is a major change (both approve + everyone notified).

`CONTRACT_VERSION = 2`

---

## 1. Folder ownership (one owner, one branch prefix)

| Folder | Owner | Branch prefix | Tool |
|---|---|---|---|
| `brain/` | Alif | `alif/*` | Claude Code + Codex |
| `infra/`, `.github/`, `docker-compose.yml`, `Makefile` | Taseen | `taseen/*` | Antigravity |
| `dashboard/` | Tamjid | `tamjid/*` | Antigravity |
| `telemetry/` (sdk, collector, simulators, db) + `shared/store.py` SupabaseStore class | Fojle | `fojle/*` | Codex |
| `eval/` (roi, harness, QA, pitch) | Orin | `orin/*` | Codex |
| `shared/` (contracts, config, store protocol, pricing, mocks), `docs/CONTRACTS.md`, `docs/ARCHITECTURE.md` | Alif + Taseen | `contract/*` | — |
| `docs/` (other), `README.md`, `AGENTS.md`, `.agents/` | Taseen | `taseen/*` | — |

Tests live **inside the owner's folder**: `brain/tests/`, `telemetry/tests/`, `eval/tests/`,
`dashboard/tests/`, `infra/tests/`. Contract tests: `shared/tests/`.

---

## 2. Ports

| Port | Service | Start command |
|---|---|---|
| 8000 | C2 REST API + WebSocket (real) **or** mock API (never both) | `python -m brain` / `python -m shared.mocks.mock_api` |
| 4318 | OTLP/HTTP collector (`POST /v1/traces`) | `python -m telemetry.collector` |
| 8501 | Dashboard | `streamlit run dashboard/app.py` |
| 8765 | MCP server, Streamable HTTP at `/mcp` (stdio needs no port) | `python -m brain.mcp_server --http` |

---

## 3. Environment variables (read ONLY via `shared.config.settings`)

| Var | Default | Used by | Meaning |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | "" | brain | Claude judge. Empty → fallback judge |
| `JUDGE_PROVIDER` | `auto` | brain | `auto` (claude if key, else gemini if key, else fallback) · `claude` · `gemini` · `fallback` |
| `CLAUDE_MODEL` | `claude-haiku-5-5` | brain | judge model |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | "", `gemini-2.5-flash` | brain | optional judge |
| `SUPABASE_URL`, `SUPABASE_KEY` | "" | store | both set → Supabase, else SQLite |
| `LOCAL_DB_PATH` | `data/cloudsentinel.db` | store | SQLite file |
| `CS_API_URL` | `http://localhost:8000` | dashboard, sdk, mcp | where the C2 API is |
| `CS_API_TOKEN` | "" | api, dashboard, sdk, mcp | if set, every request must send header `X-CS-Token` |
| `CS_API_HOST`, `CS_API_PORT` | `0.0.0.0`, `8000` | brain | API bind |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | sdk | collector base URL (standard OTel var) |
| `CS_COLLECTOR_PORT` | `4318` | collector | bind port |
| `CS_AGENT_ID` | "" | sdk | agent id if not passed to `cs.init()` |
| `CS_CAPTURE_PROMPTS` | `true` | sdk | send first 200 chars of prompts (synthetic data only!) |
| `CS_POLICY_FILE` | `brain/policies.yaml` | brain | policies |
| `EXECUTOR` | `docker` | brain | `docker` · `k8s` · `fake` (`--fake` forces fake) |
| `MONITOR_LABEL` | `cloudsentinel.monitor` | executor | only containers with `<label>=true` |
| `K8S_NAMESPACE` | `cloudsentinel` | executor | |
| `TICK_SECONDS` | `1` | brain | |
| `DRY_RUN` | `false` | brain | log actions, never execute |
| `DEFAULT_BUDGET_USD` | `0.50` | brain | per-agent session budget if policy has none |
| `SOFT_TOKENS_PER_MIN` / `HARD_TOKENS_PER_MIN` | 25000 / 60000 | brain | |
| `SOFT_CALLS_PER_SEC` / `HARD_CALLS_PER_SEC` | 2 / 8 | brain | |
| `SOFT_MEMORY_PCT` / `HARD_MEMORY_PCT` | 70 / 90 | brain | |
| `LOOP_REPEAT_THRESHOLD` | 8 | brain | exact repeats in 60 s |
| `LOOP_SCORE_THRESHOLD` | 0.6 | brain | semantic loop score (0–1) |
| `BRAIN_COOLDOWN_SECONDS` | 10 | brain | min gap between judge calls per agent |
| `BRAIN_KILL_CONFIDENCE` | 0.6 | brain | min judge confidence to act |
| `PROBATION_SECONDS` | 30 | brain | |
| `TOOL_APPROVAL_TIMEOUT_SECONDS` | 120 | sdk, api | pending tool call → auto-deny after this |
| `ROI_HORIZON_MINUTES` | 60 | eval | how far ahead "saved" burn is projected |

---

## 4. OpenTelemetry span schema (agent SDK → collector)

Transport: **OTLP/HTTP** `POST {OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces`, body
`application/x-protobuf` (standard exporter) **or** `application/json` (OTLP JSON). Response `200 {}`.

**Resource attributes** (once per process):

| Attribute | Required | Example |
|---|---|---|
| `service.name` | ✅ | `beta` (= agent id) |
| `cloudsentinel.agent.id` | ✅ | `beta` |
| `cloudsentinel.runtime` | — | `docker` · `k8s` · `local` · `fake` |

**Span types** (names and attributes follow OTel GenAI semantic conventions; `cloudsentinel.*` are ours):

| Span name | `gen_ai.operation.name` | Required attributes | Optional |
|---|---|---|---|
| `invoke_agent {agent}` | `invoke_agent` | `gen_ai.agent.name`, `gen_ai.agent.id`, `cloudsentinel.task.id` | `cloudsentinel.task.status` = `success`·`failure`·`abandoned` (set before end) |
| `chat {model}` | `chat` | `gen_ai.provider.name` (`anthropic`·`openai`·`gemini`·`sim`), `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | `cloudsentinel.prompt.preview` (≤200 chars), `cloudsentinel.prompt.hash` |
| `execute_tool {tool}` | `execute_tool` | `gen_ai.tool.name`, `gen_ai.tool.call.id` | `cloudsentinel.tool.args` (JSON ≤500 chars), `cloudsentinel.tool.decision` (`allow`·`deny`·`rewrite`·`timeout`), `cloudsentinel.tool.value_usd` |

Errors: span status `ERROR` + attribute `error.type`. `chat`/`execute_tool` spans are children of `invoke_agent`.
Agent id resolution in the collector: `cloudsentinel.agent.id` → `gen_ai.agent.id` → `service.name` → `"unknown"`.

**Normalized row** `SpanRow` (collector → `spans` table): see §5.

---

## 5. Database tables (`telemetry/db/schema.sql`, mirrored by `LocalStore`)

All timestamps: `created_at` ISO-8601 UTC text (`timestamptz` in Postgres); `*_ts` = float epoch seconds.
Every table has `id` (auto increment). Columns marked JSON are TEXT containing JSON.

| Table | Columns | Written by | Read by |
|---|---|---|---|
| `agents` (PK `agent_id`, upsert) | agent_id, display_name, runtime, runtime_id, state, budget_usd, spend_usd, total_tokens, last_seen_ts, updated_at | brain | api |
| `spans` | trace_id, span_id, parent_span_id, agent_id, operation, name, provider, model, input_tokens, output_tokens, cost_usd, tool_name, tool_args (JSON), prompt_preview, prompt_hash, task_id, task_status, status (`ok`·`error`), error_type, start_ts, end_ts, duration_ms, created_at | collector / fake fleet | brain, api, eval |
| `agent_metrics` | agent_id, state, tokens_per_min, usd_per_min, calls_per_sec, total_tokens, spend_usd, budget_usd, exact_repeats, loop_score, tool_cycle (0/1), memory_mb, memory_pct, created_at | brain | api, eval |
| `alerts` | agent_id, severity (`info`·`warning`·`critical`), rule, message, created_at | brain | api |
| `verdicts` | agent_id, source (`claude`·`gemini`·`fallback`), action (`KILL`·`PAUSE`·`WARN`·`IGNORE`), confidence, pattern, reason, suggested_fix, latency_ms, created_at | brain | api, eval |
| `actions` | agent_id, action (see enum), actor (`rules`·`claude`·`gemini`·`fallback`·`human`·`policy`·`mcp`), reason, usd_saved_estimate, tokens_saved_estimate, created_at | brain, api | api, eval |
| `commands` | agent_id, command (`KILL`·`PAUSE`·`RESUME`·`RESTART`·`GO_ROGUE`·`SET_BUDGET`), params (JSON), requested_by (`dashboard`·`mcp`·`terminal`·`eval`), reason, status (`pending`·`done`·`failed`), result, created_at | api | brain |
| `agent_memory` (append-only versions) | agent_id, version, content (JSON object), edited_by (`agent`·`human`·`mcp`), reason, created_at | api | api (SDK via API) |
| `tool_calls` | agent_id, tool_name, args (JSON), decision (`pending`·`allow`·`deny`·`rewrite`·`timeout`), final_args (JSON), decided_by (`policy`·`human`·`mcp`·`timeout`), reason, value_usd, created_at, decided_at | api | api, brain, eval |

**Enums** (in `shared/contracts.py`):
- `AgentState`: `healthy` · `suspicious` · `paused` · `probation` · `killed`
- `ActionType`: `KILL` · `PAUSE` · `RESUME` · `RESTART` · `WARN` · `SET_BUDGET` · `MEMORY_EDIT` · `TOOL_ALLOW` · `TOOL_DENY` · `TOOL_REWRITE`
- `Pattern` (judge): `infinite_loop` · `semantic_loop` · `token_spike` · `memory_leak` · `bad_tool_call` · `prompt_injection` · `legitimate_burst` · `other`

**Store protocol** (`shared/store.py`, both `LocalStore` and `SupabaseStore` must pass `shared/tests/test_store_contract.py`):

```
writes:  upsert_agent(AgentRow) · insert_spans(list[SpanRow]) · insert_metric(MetricRow) · insert_alert(AlertRow)
         insert_verdict(VerdictRow) · insert_action(ActionRow) · insert_command(CommandRow) -> int
         finish_command(id, status, result) · write_memory(agent_id, content, edited_by, reason, base_version=None) -> MemoryRow
         insert_tool_call(ToolCallRow) -> int · decide_tool_call(id, decision, final_args, decided_by, reason)
reads:   list_agents() · get_agent(id) · spans_after(last_id, limit=2000) · recent_spans(minutes, agent_id=None)
         recent_metrics(minutes, agent_id=None) · recent_alerts(limit) · recent_verdicts(limit, agent_id=None)
         recent_actions(limit) · pending_commands() · get_memory(agent_id) · memory_history(agent_id, limit)
         get_tool_call(id) · list_tool_calls(status=None, limit=50)
admin:   reset()
```
`write_memory` with `base_version` older than the latest version written by `human`/`mcp` raises
`MemoryConflict` (the API maps it to HTTP 409) — so an agent can never silently overwrite a human fix.

---

## 6. C2 REST API (`brain/api.py`, mock: `shared/mocks/mock_api.py`)

Base `http://localhost:8000`. JSON in/out. Auth: header `X-CS-Token: <CS_API_TOKEN>` when the env var is set.
Interactive docs at `/docs`. Errors: `{"detail": "..."}` with 400/404/409.

| Method + path | Body → Response | Caller |
|---|---|---|
| `GET /v1/health` | → `{"ok": true, "mode": "fake"|"docker"|"k8s"|"mock", "judge": "claude"|"gemini"|"fallback", "contract": 2}` | all |
| `GET /v1/fleet` | → `{"agents": [AgentView]}` | dashboard, mcp |
| `GET /v1/agents/{id}` | → `{"agent": AgentView, "spans": [SpanRow ≤50], "verdicts": [VerdictRow ≤10], "memory": MemoryRow|null}` | dashboard, mcp |
| `GET /v1/metrics?minutes=5&agent_id=` | → `{"metrics": [MetricRow]}` | dashboard |
| `GET /v1/graph?minutes=2` | → `{"nodes": [{"id","kind": "agent"|"tool"|"model","label"}], "edges": [{"source","target","count","in_cycle"}]}` | dashboard |
| `GET /v1/verdicts?limit=20` · `GET /v1/actions?limit=50` · `GET /v1/alerts?limit=50` | → `{"items": [...]}` | dashboard, mcp |
| `POST /v1/agents/{id}/commands` | `{"command","params":{},"requested_by","reason"}` → `{"id": int, "status": "pending"}` | dashboard, mcp |
| `GET /v1/agents/{id}/memory` | → `MemoryRow` (404 if none) | sdk, dashboard, mcp |
| `PUT /v1/agents/{id}/memory` | `{"content":{},"edited_by","reason","base_version":int|null}` → `MemoryRow` (409 on conflict) | sdk, dashboard, mcp |
| `GET /v1/agents/{id}/memory/history?limit=10` | → `{"items": [MemoryRow]}` | dashboard |
| `POST /v1/agents/{id}/tool-calls` | `{"tool_name","args":{},"value_usd":float|null}` → `ToolCallRow` (decision may be `pending`) | sdk |
| `GET /v1/tool-calls/{call_id}` | → `ToolCallRow` | sdk (polls ≤1/s) |
| `GET /v1/tool-calls?status=pending` | → `{"items": [ToolCallRow]}` | dashboard, mcp |
| `POST /v1/tool-calls/{call_id}/decision` | `{"decision": "allow"|"deny"|"rewrite","final_args":{}|null,"decided_by","reason"}` → `ToolCallRow` | dashboard, mcp |
| `GET /v1/roi` | → `RoiReport` (see §8) | dashboard, mcp |
| `WS /v1/stream` | server pushes `{"type": "metric"|"verdict"|"action"|"alert"|"tool_call","data":{...}}` | optional clients |

**`AgentView`** = `agents` row + latest metric:
`{agent_id, display_name, runtime, state, budget_usd, spend_usd, total_tokens, tokens_per_min, usd_per_min,
calls_per_sec, exact_repeats, loop_score, tool_cycle, memory_pct, last_verdict: VerdictRow|null, updated_at}`

`SET_BUDGET` params: `{"budget_usd": float}`. `GO_ROGUE` params: `{"kind": "loop"|"paraphrase_loop"|"token_bomb"|"memory_leak"|"bad_tool_call"}`.

---

## 7. MCP server (`brain/mcp_server.py`) — tools exposed to Claude Desktop / Claude Code

Server name `cloudsentinel`. Transports: stdio (default) and Streamable HTTP `:8765/mcp`.
Every tool calls the C2 API (§6) — so it works against the mock API.

| Tool | Args | Returns | Destructive? |
|---|---|---|---|
| `list_agents` | — | fleet summary (id, state, $/min, spend/budget, loop score) | no |
| `get_agent` | `agent_id` | AgentView + last verdicts + memory | no |
| `explain_agent` | `agent_id` | plain-English "why is it in this state" (latest verdict + findings) | no |
| `pause_agent` / `resume_agent` / `kill_agent` | `agent_id`, `reason` | command id | **yes** (annotated `destructiveHint`) |
| `set_budget` | `agent_id`, `budget_usd` | command id | yes |
| `get_memory` / `edit_memory` | `agent_id` / `agent_id, content, reason` | MemoryRow | edit: yes |
| `list_pending_tool_calls` | — | pending ToolCallRows | no |
| `decide_tool_call` | `call_id, decision, final_args?, reason` | ToolCallRow | yes |
| `get_roi_report` | — | RoiReport | no |

`requested_by` / `decided_by` / `edited_by` = `"mcp"` for everything sent through MCP (audit trail).

---

## 8. ROI report (`eval/roi.py` → `GET /v1/roi`)

```python
def build_report(spans: list[dict], actions: list[dict], tool_calls: list[dict], horizon_minutes: float) -> dict
```
Returns `RoiReport`:
```
{"total_spend_usd", "spend_by_agent": {id: usd}, "saved_usd", "saved_by_action": [{action_id, agent_id, action, actor, usd}],
 "interventions": int, "tool_calls_held": int, "tasks_succeeded", "cost_per_successful_task_usd",
 "horizon_minutes", "formula": str}
```
Formula (shown on the dashboard verbatim): for each KILL/PAUSE, `saved = usd_per_min_at_action × ROI_HORIZON_MINUTES`
(baseline = "no CloudSentinel": the agent keeps burning until a human notices, default 60 min);
for each TOOL_DENY/TIMEOUT, `saved = value_usd`; for TOOL_REWRITE, `saved = value_usd × (1 − new_amount/old_amount)`.
The brain fills `actions.usd_saved_estimate` with the same formula at action time.

---

## 9. Executor (`shared/contracts.py: Executor` protocol, impls in `infra/executor/`)

```python
class Executor(Protocol):
    def list_agents(self) -> list[RuntimeInfo]   # agent_id, runtime_id, runtime, status("running"|"paused"|"exited"), memory_mb, memory_pct
    def pause(self, agent_id: str) -> ExecResult     # docker pause      | k8s: scale to 0 (memory is external, so resume works)
    def resume(self, agent_id: str) -> ExecResult    # docker unpause    | k8s: scale to 1
    def kill(self, agent_id: str) -> ExecResult      # docker kill       | k8s: scale to 0 + label killed
    def restart(self, agent_id: str) -> ExecResult   # docker start      | k8s: scale to 1
    def go_rogue(self, agent_id: str, kind: str) -> ExecResult  # demo trigger (writes /tmp/go_rogue in the container)
```
`ExecResult = {ok: bool, message: str}`. Never raises for "agent not found" — returns `ok=False`.
Factory: `infra.executor.get_executor(settings) -> Executor`. Fake: `shared.mocks.fake_fleet.FakeFleet` (also generates spans).
Docker discovery: label `cloudsentinel.monitor=true`; agent id from label `cloudsentinel.agent_id`.

---

## 10. Agent SDK public API (`telemetry/sdk/cloudsentinel/`)

```python
import cloudsentinel as cs
cs.init(agent_id="beta", runtime="docker")             # sets up OTel + API client
with cs.task("refund order 4471") as t:                  # invoke_agent span
    mem = cs.memory.get()                                # dict (latest version, {} if none)
    with cs.llm_call(model="claude-haiku-5-5", provider="anthropic", prompt=p) as call:   # chat span
        ...; call.record(input_tokens=..., output_tokens=...)
    result = cs.tool("issue_refund", {"amount": 50000}, fn=issue_refund, value_usd=410.0)  # gate + execute_tool span
    cs.memory.set({**mem, "last_order": 4471})          # 409 → SDK reloads and returns False
    t.success()                                          # or t.failure("reason")
```
`cs.tool` raises `cs.ToolDenied` when the decision is deny/timeout; on `rewrite` it calls `fn(**final_args)`.
If the API is unreachable the SDK **fails open** (telemetry is best-effort, tools run) unless the call passes
`cs.tool(..., fail_closed=True)` — use that for money-moving tools.
The gate also **denies every tool call from an agent the breaker has paused or killed** (second enforcement layer
for agents whose container cannot be frozen, e.g. external OTel agents).

---

## 11. Policy file (`brain/policies.yaml`)

```yaml
defaults:
  budget_usd: 0.50          # session budget per agent
  on_trip: pause            # what a confident judge PAUSE/KILL does: pause | kill
  on_hard_limit: kill       # pause | kill
agents:
  delta: { budget_usd: 0.20 }
tools:                      # first match wins; glob on tool name
  - { match: "delete_*",     action: deny,     reason: "destructive tools are never allowed" }
  - { match: "issue_refund", action: approval, when: { arg: amount, op: gt, value: 5000 },
      reason: "refunds over 5,000 BDT need a human" }
  - { match: "*",            action: allow }
```
`op` ∈ `gt, gte, lt, lte, eq, ne, contains`. No `eval()` — ever.
