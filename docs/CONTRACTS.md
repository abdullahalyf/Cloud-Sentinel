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
| 5173 | Web dashboard (React + Vite dev server, proxies `/v1` → :8000). In compose: nginx on 5173 | `cd dashboard/web && npm run dev` |
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
| `BRAIN_KILL_CONFIDENCE` | 0.6 | brain | min judge confidence to act — a PAUSE below it is a WARN in practice |
| `PROBATION_SECONDS` | 30 | brain | |
| `CS_AUTOHEAL` *(added 8 Nov)* | `true` | brain | apply a confident judge patch automatically; false → every patch waits for a human |
| `CS_AUTOHEAL_MIN_CONFIDENCE` *(added 8 Nov)* | `0.85` | brain | judge confidence at or above which a patch is applied without a human |
| `CS_VERIFIED_HEAL` *(added 8 Nov, B1)* | `false` | brain | before a judge patch is applied, replay the agent's recent context against it in a **shadow dry-run**; apply automatically only if the shadow is healthy **and** the confidence is at least `CS_AUTOHEAL_MIN_CONFIDENCE`, otherwise the patch goes to the approvals inbox. `false` → every patch waits for a human (the A3 behaviour, exactly) |
| `CS_DEGRADATION_ENABLED` *(added 8 Nov, B4)* | `false` | brain | step a runaway agent down the ladder — throttle → cheaper model → pause → kill — one rung at a time. `false` → the old behaviour exactly (pause or kill, straight away, no throttle) |
| `CS_BUDGET_WARN_USD_PER_MIN` *(added 8 Nov, B4)* | `0` | brain | the burn rate at which the brain warns that a budget is going to run out; `0` → no warning |
| `CS_BASELINE_ENABLED` *(added 8 Nov)* | `true` | brain | learn per-agent limits from healthy behaviour; false → the fixed soft limits only |
| `CS_BASELINE_WARMUP_SECONDS` *(added 8 Nov)* | `60` | brain | how long an agent runs on the fixed soft limits before its own baseline is used |
| `CS_BASELINE_K` *(added 8 Nov)* | `4` | brain | MAD multiplier of the adaptive limit (limit = median + K × 1.4826 × MAD) |
| `CS_POLICY_RELOAD_ENABLED` *(added 8 Nov)* | `true` | brain | pick up a changed `CS_POLICY_FILE` while running; false → the policy is read once at startup |
| `CS_POLICY_RELOAD_INTERVAL_SECONDS` *(added 8 Nov)* | `1` | brain | how often the policy file's mtime is checked |
| `CS_INJECTION_ENABLED` *(added 8 Nov)* | `true` | brain | score agent text and tool arguments for prompt injection; false → the gate trusts the policy only |
| `CS_INJECTION_DENY_THRESHOLD` *(added 8 Nov)* | `0.8` | brain | injection score at or above which the tool gate **denies** the call |
| `CS_INJECTION_APPROVAL_THRESHOLD` *(added 8 Nov)* | `0.5` | brain | injection score at or above which the tool gate asks a **human** (below the deny threshold) |
| `CS_INJECTION_MEMORY_THRESHOLD` *(added 8 Nov)* | `0.5` | brain | injection score at or above which an agent memory write raises an alert |
| `CS_INJECTION_ALLOWED_HOSTS` *(added 8 Nov)* | `api.shopbd.com,localhost,127.0.0.1,example.com` | brain | comma-separated hosts a tool argument may point at; any other host is a finding |
| `CS_MCP_READONLY` *(added 8 Nov)* | `false` | mcp | expose only the MCP tools that change nothing; a read-only client cannot pause anything |
| `CS_MCP_RATE_LIMIT` *(added 8 Nov)* | `30` | mcp | destructive MCP calls per minute, per session; reads are never throttled |
| `CS_MCP_HTTP_HOST` *(added 8 Nov)* | `127.0.0.1` | mcp | the address the MCP HTTP transport binds; a non-localhost bind needs `CS_API_TOKEN` or the server refuses to start |
| `CS_MCP_HTTP_PORT` *(added 8 Nov)* | `8765` | mcp | the port the MCP HTTP transport binds |
| `CS_WORKER_ID` *(added 8 Nov)* | "" | brain | this brain worker's id; empty → one generated from the pid |
| `CS_WORKER_HEARTBEAT_SECONDS` *(added 8 Nov)* | `2` | brain | how often a worker writes its heartbeat into the `workers` table |
| `CS_WORKER_STALE_SECONDS` *(added 8 Nov)* | `10` | brain | a worker that has not beaten for this long is dead, and its agents are taken over |
| `TOOL_APPROVAL_TIMEOUT_SECONDS` | 120 | sdk, api | pending tool call → auto-deny after this |
| `ROI_HORIZON_MINUTES` | 60 | eval | how far ahead "saved" burn is projected |
| `CS_EXPORT_PHOENIX` *(added 4 Nov)* | `false` | collector | also forward every OTLP batch to Arize Phoenix (background, never blocks) |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | collector | Phoenix base URL; spans go to `…/v1/traces` |
| `PHOENIX_API_KEY` | "" | collector | sent as `Authorization: Bearer …` (Phoenix Cloud) |
| `PHOENIX_PROJECT_NAME` | `cloudsentinel` | collector | Phoenix project (resource `openinference.project.name`) |
| `CS_EXPORT_CLOUDWATCH` *(added 5 Nov)* | `false` | collector | also write every stored span as a CloudWatch EMF JSON line |
| `CS_CLOUDWATCH_FILE` *(added 5 Nov)* | `data/cloudwatch.jsonl` | collector | where the EMF lines go |
| `CS_JUDGE_MAX_USD_PER_HOUR` *(added 8 Nov)* | `0` | brain | what the LLM judge may cost in one hour; above it the brain uses the deterministic fallback and writes a `judge_cost_capped` alert. `0` = no cap |
| `CS_VERDICT_OTLP_ENDPOINT` *(added 8 Nov, A15)* | `` (empty) | brain | the collector the brain sends its verdict spans to, so the verdict lands on the agent's own OTel trace (see §4, `cs_verdict`). Empty = off; the brain keeps working either way |

**Tuned defaults.** `SOFT_MEMORY_PCT`, `LOOP_REPEAT_THRESHOLD`, `LOOP_SCORE_THRESHOLD` and
`BRAIN_KILL_CONFIDENCE` are not guesses: `python -m brain.tuning` grid-searches them against the
64 labelled incidents in `brain/eval_data/incidents.jsonl` and writes the winner to `brain/tuning.json`.
The objective is *zero false positives first, then max recall* — a judge that stops healthy agents is
worse than no judge, because operators learn to ignore it. The current winner (fallback judge)
reaches precision 1.000 / recall 0.806 / F1 0.893 with **no** false positives. Re-run
`python -m brain.tuning --judge fallback` after changing any of them; `brain/tests/test_tuning.py`
fails if the defaults drift away from the winner.

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
| `graph_node {node}` *(added 4 Nov, additive)* | `graph_node` | `cloudsentinel.node.name` | `cloudsentinel.node.step` (int), `cloudsentinel.node.framework` (`langgraph`·`crewai`·`custom`), `cloudsentinel.node.state_delta` (JSON `{key: preview ≤60 chars}`, ≤8 keys), `cloudsentinel.node.next` (where the graph routed) |
| `cs_verdict {agent}` *(added 8 Nov, A15, additive)* | `cs_verdict` | `cloudsentinel.agent.id` | `cloudsentinel.verdict.action` (`PAUSE`·`KILL`·`WARN`·…), `cloudsentinel.verdict.source` (`claude`·`gemini`·`fallback`·`rules`), `cloudsentinel.verdict.confidence` (0–1), `cloudsentinel.verdict.reason` (≤300 chars), `cloudsentinel.loop.score` (0–1), `cloudsentinel.loop.exact_repeats` (int) |
| `cs_verdict {agent}` — `verified_heal` event *(added 8 Nov, B1, additive)* | `cs_verdict` | `cloudsentinel.agent.id` | `cloudsentinel.heal.shadow_verdict` (`healthy`·`still_bad`·`no_opinion`), `cloudsentinel.heal.applied` (bool), `cloudsentinel.heal.confidence` (0–1), `cloudsentinel.heal.loop_score_before` (0–1), `cloudsentinel.heal.loop_score_after` (0–1), `cloudsentinel.heal.reason` (≤300 chars) |

Errors: span status `ERROR` + attribute `error.type`. `chat`/`execute_tool` spans are children of `invoke_agent`,
or of the `graph_node` they ran in. `graph_node` is a CloudSentinel extension (OTel GenAI has no "graph node" yet):
one span per LangGraph node run or CrewAI task, emitted by `cloudsentinel.adapters.langgraph` / `.crewai` or `cs.node()`.
Agent id resolution in the collector: `cloudsentinel.agent.id` → `gen_ai.agent.id` → `service.name` → `"unknown"`.

**`cs_verdict` — the brain's verdict, on the agent's own trace (A15).** The brain watches an agent's
spans and decides what to do with it. That decision used to live only in CloudSentinel's tables,
while the *behaviour* that caused it lived on the agent's OpenTelemetry trace — so the cause and
the effect were on two different screens, and somebody had to join them by hand.

A `cs_verdict` span is emitted **by the brain**, over OTLP/HTTP to the collector, carrying:

- the **agent's own `trace_id`**, with the judged span as its `parent_span_id` — so the verdict is
  a child of the behaviour that caused it, on the same trace;
- a **span event named `semantic_loop`**, carrying the same attributes as the span. The event is
  what makes it read as *"something happened at this point in the trace"* rather than *"this span
  was described this way"*;
- the **numbers** — the loop score, the repeat count, the confidence. A verdict without its
  evidence is an opinion.

The collector forwards the **raw OTLP body** to Phoenix (`phoenix.submit(body, ctype)`), not the
rows it normalized out of it — and the span event only exists in the raw body. So the event
survives all the way to Phoenix without a line changing in `telemetry/`.

An agent that is not instrumented has no trace to attach to; the verdict is still emitted, just
without a parent.

**`cs_verdict` — the `verified_heal` event (B1).** When the judge proposes a patch, the brain may
replay the agent's recent context against it in a **shadow dry-run** before touching the agent. The
whole flow — the shadow's verdict, the loop score before and after, the confidence and whether the
patch was applied — rides on the same `cs_verdict` span as a second span event named
`verified_heal`. It is a separate event (not extra attributes on `semantic_loop`) because it is a
different moment in time: the shadow ran *before* the agent was touched, and a reader must be able
to see the proof and the decision side by side.

**Normalized row** `SpanRow` (collector → `spans` table): see §5.

---

## 5. Database tables (`telemetry/db/schema.sql`, mirrored by `LocalStore`)

All timestamps: `created_at` ISO-8601 UTC text (`timestamptz` in Postgres); `*_ts` = float epoch seconds.
Every table has `id` (auto increment). Columns marked JSON are TEXT containing JSON.

| Table | Columns | Written by | Read by |
|---|---|---|---|
| `agents` (PK `agent_id`, upsert) | agent_id, display_name, runtime, runtime_id, state, budget_usd, spend_usd, total_tokens, last_seen_ts, baseline (JSON), updated_at | brain | api |
| `spans` | trace_id, span_id, parent_span_id, agent_id, operation, name, provider, model, input_tokens, output_tokens, cost_usd, tool_name, tool_args (JSON), prompt_preview, prompt_hash, task_id, task_status, status (`ok`·`error`), error_type, start_ts, end_ts, duration_ms, detail (JSON; `graph_node`: `{node, step, framework, changed, next}`, else `{}`), created_at | collector / fake fleet | brain, api, eval |
| `agent_metrics` | agent_id, state, tokens_per_min, usd_per_min, calls_per_sec, total_tokens, spend_usd, budget_usd, exact_repeats, loop_score, tool_cycle (0/1), memory_mb, memory_pct, created_at | brain | api, eval |
| `alerts` | agent_id, severity (`info`·`warning`·`critical`), rule, message, created_at | brain | api |
| `verdicts` | agent_id, source (`claude`·`gemini`·`fallback`), action (`KILL`·`PAUSE`·`WARN`·`IGNORE`), confidence, pattern, reason, suggested_fix, latency_ms, created_at | brain | api, eval |
| `actions` | agent_id, action (see enum), actor (`rules`·`claude`·`gemini`·`fallback`·`human`·`policy`·`mcp`), reason, usd_saved_estimate, tokens_saved_estimate, created_at | brain, api | api, eval |
| `commands` | agent_id, command (`KILL`·`PAUSE`·`RESUME`·`RESTART`·`GO_ROGUE`·`SET_BUDGET`), params (JSON), requested_by (`dashboard`·`mcp`·`terminal`·`eval`), reason, status (`pending`·`done`·`failed`), result, created_at | api | brain |
| `agent_memory` (append-only versions) | agent_id, version, content (JSON object), edited_by (`agent`·`human`·`mcp`), reason, created_at | api | api (SDK via API) |
| `tool_calls` | agent_id, tool_name, args (JSON), decision (`pending`·`allow`·`deny`·`rewrite`·`timeout`), final_args (JSON), decided_by (`policy`·`human`·`mcp`·`timeout`), reason, value_usd, created_at, decided_at | api | api, brain, eval |
| `heal_proposals` *(added 8 Nov)* | agent_id, kind (`memory_patch`·`tool_policy`), patch (JSON), confidence, status (`pending`·`applied`·`rejected`·`expired`), verdict_id, base_version, reason, decided_by (`human`·`mcp`·`brain:autoheal`), decided_at, created_at | brain, api | api, dashboard, mcp |
| `schema_migrations` *(added 5 Nov)* | version (PK, migration file name), applied_at | `telemetry/db/migrate.py` | migrate.py |
| `workers` *(added 8 Nov, A8)* | worker_id (PK), started_at (float, when the worker came up), last_seen (float, last heartbeat), agents_owned (int), pid | brain workers | brain, api (`/v1/health`) |

**Enums** (in `shared/contracts.py`):
- `AgentState`: `healthy` · `suspicious` · `paused` · `probation` · `killed`
- `ActionType`: `KILL` · `PAUSE` · `RESUME` · `RESTART` · `WARN` · `SET_BUDGET` · `MEMORY_EDIT` · `TOOL_ALLOW` · `TOOL_DENY` · `TOOL_REWRITE` · `AUTO_HEAL`
- `Pattern` (judge): `infinite_loop` · `semantic_loop` · `token_spike` · `memory_leak` · `bad_tool_call` · `prompt_injection` · `legitimate_burst` · `other`
- `HealKind`: `memory_patch` · `tool_policy` · `HealStatus`: `pending` · `applied` · `rejected` · `expired`

**Store protocol** (`shared/store.py`, both `LocalStore` and `SupabaseStore` must pass `shared/tests/test_store_contract.py`):

```
writes:  upsert_agent(AgentRow) · insert_spans(list[SpanRow]) · insert_metric(MetricRow) · insert_alert(AlertRow)
         insert_verdict(VerdictRow) · insert_action(ActionRow) · insert_command(CommandRow) -> int
         finish_command(id, status, result) · write_memory(agent_id, content, edited_by, reason, base_version=None) -> MemoryRow
         insert_tool_call(ToolCallRow) -> int · decide_tool_call(id, decision, final_args, decided_by, reason)
         insert_heal_proposal(HealProposalRow) -> int · decide_heal_proposal(id, status, decided_by, reason)
         heartbeat_worker(worker_id, started_at, last_seen, agents_owned, pid=0)
reads:   list_agents() · get_agent(id) · spans_after(last_id, limit=2000) · recent_spans(minutes, agent_id=None)
         recent_metrics(minutes, agent_id=None) · recent_alerts(limit) · recent_verdicts(limit, agent_id=None)
         recent_actions(limit) · pending_commands() · get_memory(agent_id) · memory_history(agent_id, limit)
         get_tool_call(id) · list_tool_calls(status=None, limit=50)
         get_heal_proposal(id) · list_heal_proposals(status=None, agent_id=None, limit=50)
         list_workers(seen_within_seconds=None) · remove_worker(worker_id)
admin:   reset()
```
`heartbeat_worker` keeps `started_at` across heartbeats — it is when the worker came up, not the
time of the last beat, so a worker's uptime must not reset every two seconds.
`write_memory` with `base_version` older than the latest version written by `human`/`mcp` raises
`MemoryConflict` (the API maps it to HTTP 409) — so an agent can never silently overwrite a human fix.

---

## 6. C2 REST API (`brain/api.py`, mock: `shared/mocks/mock_api.py`)

Base `http://localhost:8000`. JSON in/out. Auth: header `X-CS-Token: <CS_API_TOKEN>` when the env var is set.
Interactive docs at `/docs`. Errors: `{"detail": "..."}` with 400/404/409.

| Method + path | Body → Response | Caller |
|---|---|---|
| `GET /v1/health` | → `{"ok": true, "mode": "fake"|"docker"|"k8s"|"mock", "judge": "claude"|"gemini"|"fallback", "contract": 2}` | all |
| `GET /v1/health` *(added 8 Nov, A8)* | the same, plus `"workers": [{"worker_id", "started_at", "last_seen", "agents_owned", "pid"}]` and `"agents_total": int` — one entry per live worker, and how many agents the fleet has between them | all |
| `GET /v1/fleet` | → `{"agents": [AgentView]}` | dashboard, mcp |
| `GET /v1/agents/{id}` | → `{"agent": AgentView, "spans": [SpanRow ≤50], "verdicts": [VerdictRow ≤10], "memory": MemoryRow|null}` | dashboard, mcp |
| `GET /v1/agents/{id}/nodes?minutes=10&limit=100` *(added 4 Nov)* | → `NodeFeed` (below) | dashboard |
| `GET /v1/agents/{id}/explain?minutes=10` *(added 8 Nov, A13)* | → `ExplainReport` (below) — the deterministic summary of what happened, and why | dashboard, mcp |
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
| `GET /v1/tool-risk?agent_id=` *(added 8 Nov, A14)* | → `ToolRiskReport` (below) — what a human has approved, per (agent, tool, args) | dashboard, mcp |
| `GET /v1/incidents/{id}/postmortem` *(added 8 Nov, B2)* | → `PostmortemReport` (below) — the structured postmortem of one incident | dashboard, mcp |
| `GET /v1/incidents/{id}/postmortem.md` *(added 8 Nov, B2)* | → the same postmortem as markdown (`text/markdown`) | dashboard, mcp |
| `GET /v1/heal-proposals?status=&agent_id=&limit=50` *(added 8 Nov)* | → `{"items": [HealProposalRow]}` | dashboard, mcp |
| `POST /v1/heal-proposals/{id}/decision` *(added 8 Nov)* | `{"decision": "apply"|"reject","reason","requested_by"}` → `HealProposalRow` | dashboard, mcp |
| `GET /v1/roi` | → `RoiReport` (see §8) | dashboard, mcp |
| `GET /v1/policy` *(added 8 Nov)* | → `PolicyView` (below) | dashboard, mcp |
| `POST /v1/policy/reload` *(added 8 Nov)* | → `{"ok": true, "policy": PolicyView}` — re-reads the file now; `ok:false` + the errors in `policy.last_error` if it is broken | dashboard, mcp |
| `POST /v1/policy/validate` *(added 8 Nov)* | `{"yaml": "..."}` → `{"ok": bool, "errors": ["tools[2].when.op: must be one of …"]}` — validates YAML text, changes nothing | dashboard, mcp |
| `GET /v1/budgets` *(added 8 Nov, B4)* | → `BudgetReport` (below) — the org → team → agent budget tree, with a burn-rate forecast at every level | dashboard, mcp |
| `WS /v1/stream` | server pushes `{"type": "metric"|"verdict"|"action"|"alert"|"tool_call","data":{...}}` | optional clients |

**`PolicyView`** *(added 8 Nov)* — the policy actually in force:
`{version: str, loaded_at: str, source: str, defaults: {...}, agents: {...}, tools: [...], last_error: str}`.
`version` is `sha256(policy file)[:12]` — it changes whenever the file changes. `last_error` is empty while
the policy is good, and holds the validation errors of the **rejected** file otherwise (the last good
policy stays in force).

**`AgentView`** = `agents` row + latest metric:
`{agent_id, display_name, runtime, state, budget_usd, spend_usd, total_tokens, tokens_per_min, usd_per_min,
calls_per_sec, exact_repeats, loop_score, tool_cycle, memory_pct, baseline: {metric: {median, limit, samples}},
last_verdict: VerdictRow|null, updated_at}`

**`baseline`** *(added 8 Nov)* — the agent's own learned limits, so the dashboard can say "normal for this
agent". `{metric: {median: float, limit: float, samples: int}}` for `tokens_per_min`, `usd_per_min` and
`calls_per_sec`. Empty `{}` while the agent is still in warmup.

**`NodeFeed`** (LangGraph/CrewAI flow, oldest → newest):
`{"items": [{ts, node, step, framework, changed: {key: preview}, next, status, duration_ms, trace_id}],
"edges": [{source, target, count}], "last_node": str|null, "next_node": str|null}`. `edges` count transitions
between consecutive nodes of the same run (`trace_id`), so a loop shows as A→B and B→A with growing counts.

**`ExplainReport`** *(added 8 Nov, A13)* — "what happened to this agent, and why":

```
{
  "agent_id": str,
  "state": str,                 # the agent's current state (healthy | suspicious | paused | ...)
  "minutes": float,             # the window the report covers
  "summary": str,               # one plain-English paragraph — the deterministic text
  "polished_summary": str|null, # a Claude rewrite of `summary`, or null when there is no key
  "events": [                  # oldest → newest; the chain that led here
    {"kind": "alert"|"verdict"|"action"|"heal",
     "ts": float, "title": str, "detail": str}
  ],
  "counts": {"alerts": int, "verdicts": int, "actions": int, "heals": int},
  "outcome": str|null,          # what finally happened: PAUSE | KILL | WARN | IGNORE | null
  "cost": {"spend_usd": float, "budget_usd": float, "saved_usd": float}
}
```

**The summary is deterministic.** The same agent and the same store always produce the same
paragraph, with no key and no network — that is what makes it testable (a golden-text test) and
what makes it safe to cache. `polished_summary` is the optional extra: when a Claude key is
present the server asks Claude to rewrite `summary` into something smoother, and puts the result
there. **When there is no key, `polished_summary` is `null` and `summary` is the whole answer** —
the endpoint never fails and never blocks on the network. A client must render `polished_summary`
when it is there and fall back to `summary` when it is `null`.

**The chain is the point.** `events` is the story in order — the alerts that fired, the verdicts
the judge reached, the actions the breaker took, the heals that were applied — so an operator
reads *why* the agent is in this state instead of guessing from the current metrics. The
`outcome` is the last thing that happened to it.

**An unknown agent is a 404**, the same on both sides: an explanation of nothing would be a
confident paragraph about an agent nobody has ever heard of. `minutes` is a real window — an event
older than the window is not in the report — and it is clamped to 24 hours.

**`BudgetReport`** *(added 8 Nov, B4)* — the budget tree and the forecast on it:

```
{
  "org": BudgetNode,
  "teams": [BudgetNode],
  "agents": [BudgetNode],
  "as_of": float|null
}

BudgetNode = {
  "level": "org"|"team"|"agent",
  "id": str,
  "budget_usd": float,
  "spend_usd": float,
  "remaining_usd": float,     # max(0, budget - spend) — never negative
  "children": [str],          # the ids one level down; [] at the agent level
  "forecast": BudgetForecast
}

BudgetForecast = {
  "remaining_usd": float,
  "usd_per_min": float,
  "minutes_to_exhausted": float|null,   # null when the burn rate is 0
  "horizon_minutes": float,
  "sentence": str,                      # "" when there is nothing to say
  "exhausted_within_horizon": bool
}
```

**The budget is a tree, and every level is the sum of the level below.** The org budget is the sum
of the team budgets, and a team budget is the sum of its agents' budgets. That is not decoration:
it is what stops one runaway agent from eating the whole fleet's money — the agent overruns its
*own* share, and the tree says so out loud.

**The forecast only speaks when it can.** `minutes_to_exhausted` is `remaining / burn_rate`. A burn
rate of **zero** has no forecast: the answer would be "in 0 minutes", which is a lie, or "in
infinity", which is not a number. So `minutes_to_exhausted` is `null` and `sentence` is `""` —
the endpoint still answers, it just says nothing it cannot know. A budget already spent is a
different case: `remaining_usd` is `0.0`, `minutes_to_exhausted` is `0.0`, and the sentence says
so plainly.

**The degradation ladder** *(added 8 Nov, B4)* — how a budget is defended, gentlest first:

```
DEGRADATION_LADDER = ("THROTTLE", "DOWNGRADE", "PAUSE", "KILL")
```

`THROTTLE` slows the agent down, `DOWNGRADE` moves it to a cheaper model, `PAUSE` stops it, `KILL`
ends it. **The ladder never skips a rung.** An agent that has not been throttled is not
downgraded; the plan says which rung comes next and which rungs must be walked first. A step that
is not on the ladder (`WARN`, say) is not a rung and must not move the ladder along.

`THROTTLE` and `DOWNGRADE` are new action types, so `ACTION_TYPES` grows to include them. Every
new behaviour is behind a config flag, default **off**: with the flag off the old behaviour
(pause / kill, no throttle) is exactly what happens.

Agents **without a container** (a LangGraph/CrewAI process, any external OTel agent) are still controllable:
PAUSE/KILL are enforced by the SDK — the tool gate denies every tool call, and `cs.wait_if_paused()` (called by
the adapters before every node / LLM call) blocks while paused and raises `AgentKilled` when killed.

**`PostmortemReport`** *(added 8 Nov, B2)* — the postmortem of one incident:

```
{
  "incident_id": int,            # the alert id — an incident *is* an alert
  "agent_id": str,
  "root_cause": {
    "rule": str,                 # the rule that fired (never "unknown" if one did)
    "pattern": str,              # the pattern the judge saw (falls back to the rule)
    "detector": str,             # "rules" | "judge"
    "headline": str,             # "loop_semantic — semantic_loop", or the rule alone
    "reason": str                # the judge's own words, "" when it said nothing
  },
  "timeline": [                  # oldest → newest; the order is the point
    {"kind": "evidence"|"alert"|"verdict"|"action"|"heal",
     "ts": float, "title": str, "detail": str, "ref": str|null}
  ],
  "evidence": [                  # the real span ids — not a summary of them
    {"span_id": str, "trace_id": str, "operation": str, "start_ts": float}
  ],
  "money": {
    "usd_saved": float,          # 0.0 when nothing was saved
    "tokens_saved": int,         # 0 when nothing was saved
    "spend_usd": float,
    "formula": str               # the ROI formula (§8) that produced the number
  },
  "timings": {
    "time_to_detect_seconds": float|null,  # first evidence → alert
    "time_to_heal_seconds": float|null,    # alert → the action that fixed it
    "detected_at": float|null,
    "healed_at": float|null
  },
  "resolution": str              # what finally happened: PAUSE | KILL | ... | ""
}
```

**An incident *is* an alert.** There is no separate incident table: an incident is the moment the
brain flagged an agent and said "something is wrong here". The verdict that followed, the action
that was taken and the heal that fixed it are all part of *that* incident — so the incident id is
the alert id, and `GET /v1/incidents/{id}/postmortem` 404s for an id no alert ever had.

**The order is the point.** The timeline is sorted by time, so an alert can never precede the
verdict that caused it. A timeline whose entries cannot be traced back to a row or a span is a
story, not a record — hence `ref` on every event and the *real* `span_id`/`trace_id` in `evidence`.

**A number that cannot be measured is `null`, never a made-up zero.** "0.0 seconds" and "we do
not know" are different facts and only one of them is true, so an unmeasurable
`time_to_detect_seconds` is `null`. In the markdown it reads "not measured".

**The markdown renders the JSON, it never recomputes it.** `GET /v1/incidents/{id}/postmortem.md`
returns the same numbers as the JSON endpoint — a report that says "$0.12 saved" when the JSON
says `0.12` is a report nobody can trust. The shape and the renderer live in `shared/contracts.py`,
so the mock and the real API say the same thing.

**`ToolRiskReport`** *(added 8 Nov, A14)* — what a human has approved, per (agent, tool, args):

```
{
  "entries": [
    {
      "agent_id": str,
      "tool_name": str,
      "args": {},                  # the arguments the approvals were for
      "signature": str,           # tool + args, canonical (key order does not matter)
      "approvals": int,           # how many humans said yes to this exact call
      "denials": int,             # how many humans said no
      "threshold": int,           # how many approvals auto-approve (5)
      "auto_approved": bool,      # may this call go through without a human?
      "reason": str               # why — a client must never have to guess
    }
  ],
  "counts": {"entries": int, "auto_approved": int, "denied": int},
  "threshold": int
}
```

**Only a human answer counts.** A `policy` allow is the rules doing their job, and an `mcp`
answer is another agent's opinion — neither is a person saying "yes, this is fine", so neither
may teach the brain to stop asking. Only `decided_by: "human"` with `decision: "allow"` counts as
an approval; `decision: "deny"` counts as a denial.

**A denial is a veto.** A call a human refused is never auto-approved, however many approvals
arrive later — the counts stay in the entry, so a client can show "five said yes, one said no",
but `auto_approved` is false. `threshold` is 5: five approvals of the *identical* call (the same
tool, the same arguments) and the brain stops asking.

**The learned score never loosens a deny.** It only turns a call that would have been held for
approval into one that is allowed. A policy rule that says `deny`, and the injection gate, both
still win — the brain learns to stop asking about *safe* calls, never to wave a dangerous one
through. Every auto-approval is written to the audit log as a `TOOL_AUTO_ALLOW` action by the
`brain:toolrisk` actor, so an operator can always see which calls went through on their own.

`SET_BUDGET` params: `{"budget_usd": float}`. `GO_ROGUE` params: `{"kind": "loop"|"paraphrase_loop"|"token_bomb"|"memory_leak"|"bad_tool_call"|"prompt_injection"|"tool_storm"|"memory_poisoning"|"slow_budget_leak"}` (the last 4 added 5 Nov; implemented by the telemetry simulator, FakeFleet keeps them healthy).

### The mock may lead the real API

The mock (dashboard development) and the real API are in **different folders**, so a change to one
cannot land in the same PR as the other. The contract lands the mock first; the brain branch that
implements the same shape on the real API follows it. In between, the mock has fields the real API
does not have yet.

The rule is one-sided: **the mock may lead, the mock may never lag.** Every field the real API has
must also be in the mock, so a client written against the mock keeps working against the real
thing (`shared/tests/test_api_parity.py`).

The gaps are recorded here, and the table is empty when there are none:

| Endpoint | Fields the mock has and the real API does not (yet) | Closed by |
|---|---|---|
| `GET /v1/budgets` *(B4)* — the whole endpoint | the budget tree, the forecast, the ladder | the B4 brain PR |

When the brain side lands, delete its row — it is a record of a gap, not a permanent difference.
A8's gap (`/v1/health`: `workers`, `agents_total`) closed when `b22d509` merged.
A13's gap (`GET /v1/agents/{id}/explain`: the whole endpoint) closed when the brain side landed
as PR #47.
A14's gap (`GET /v1/tool-risk`: the whole endpoint) closed when the brain side landed as PR #51.
B2's gap (`GET /v1/incidents/{id}/postmortem` · `.md`: the whole endpoint) closed when the brain
side landed as PR #63.

---

## 7. MCP server (`brain/mcp_pkg/`, installed as `cloudsentinel-mcp`) — tools exposed to Claude Desktop / Claude Code

Server name `cloudsentinel`. Transports: stdio (default) and Streamable HTTP `:8765/mcp`.
Every tool calls the C2 API (§6) — so it works against the mock API.

**One implementation.** The server lives in `brain/mcp_pkg/cloudsentinel_mcp/` and is packaged as
`cloudsentinel-mcp`. It needs only `httpx` and `mcp` at runtime and does **not** import `shared/`,
so it installs on its own (a laptop, Claude Desktop, a container that has never seen this repo).
`brain/mcp_server.py` is a thin wrapper over it, so `python -m brain.mcp_server` and the installed
`cloudsentinel-mcp` command behave identically. See `brain/MCP.md`.

| Tool | Args | Returns | Destructive? |
|---|---|---|---|
| `list_agents` | — | fleet summary (id, state, $/min, spend/budget, loop score) | no |
| `get_agent` | `agent_id` | AgentView + last verdicts + memory | no |
| `explain_agent` | `agent_id` | plain-English "why is it in this state" — the `summary` of `GET /v1/agents/{id}/explain` (A13) | no |
| `pause_agent` / `resume_agent` / `kill_agent` | `agent_id`, `reason` | command id | **yes** (annotated `destructiveHint`) |
| `set_budget` | `agent_id`, `budget_usd` | command id | yes |
| `get_memory` / `edit_memory` | `agent_id` / `agent_id, content, reason` | MemoryRow | edit: yes |
| `list_pending_tool_calls` | — | pending ToolCallRows | no |
| `get_tool_risk` *(added 8 Nov, A14)* | `agent_id?` | ToolRiskReport — what a human has approved, per (agent, tool, args) | no |
| `decide_tool_call` | `call_id, decision, final_args?, reason` | ToolCallRow | yes |
| `list_heal_proposals` *(added 8 Nov)* | — | pending HealProposalRows | no |
| `decide_heal` *(added 8 Nov)* | `proposal_id, decision, reason` | HealProposalRow | **yes** (annotated `destructiveHint`) |
| `get_roi_report` | — | RoiReport | no |
| `get_policy` *(added 8 Nov)* | — | PolicyView (the policy in force) | no |
| `validate_policy` *(added 8 Nov)* | `yaml: str` | `{"ok": bool, "errors": [...]}` | no |

`requested_by` / `decided_by` / `edited_by` = `"mcp"` for everything sent through MCP (audit trail).

**Safety rules.** These are part of the contract, not implementation detail:

- **Input validation.** Every argument is checked before it reaches the API: the agent id must be a
  short safe identifier (it goes into a URL), the reason must be present and under 500 characters,
  the decision must be one of the allowed values, the budget must be a finite number in range. A bad
  argument comes back as a readable message — *"reason is required — it is written to the audit log"* —
  never a stack trace.
- **Rate limit.** Destructive calls are capped per session (`CS_MCP_RATE_LIMIT`, 30/min by default).
  Reads are never throttled — a dashboard should not be rate limited.
- **Read-only mode.** `CS_MCP_READONLY=true` (or `--readonly`) hides every write tool, so a
  read-only client cannot pause anything even by accident.
- **The HTTP bind needs a token.** `--http` on a non-localhost bind refuses to start unless
  `CS_API_TOKEN` is set: a public bind without a token is a remote-control surface for the fleet.
  The server shuts down instead of serving it.
- **Annotated tools.** Every tool declares `readOnlyHint` and `destructiveHint`, and a test checks
  that the annotation agrees with what the tool actually does. A tool in neither set fails the test —
  an un-audited tool cannot ship.

---

## 8. ROI report (`eval/roi.py` → `GET /v1/roi`)

```python
def build_report(spans: list[dict], actions: list[dict], tool_calls: list[dict], horizon_minutes: float) -> dict
```
Returns `RoiReport`:
```
{"total_spend_usd", "spend_by_agent": {id: usd}, "saved_usd", "saved_by_action": [{action_id, agent_id, action, actor, usd}],
 "interventions": int, "tool_calls_held": int, "tasks_total", "tasks_succeeded", "cost_per_successful_task_usd",
 "wasted_usd", "tasks_by_agent": {id: TaskStats}, "horizon_minutes", "formula": str}
TaskStats = {tasks, succeeded, failed, abandoned, success_rate, spend_usd, wasted_usd, unattributed_usd, cost_per_success_usd}
```
Formula (shown on the dashboard verbatim): for each KILL/PAUSE, `saved = usd_per_min_at_action × ROI_HORIZON_MINUTES`
(baseline = "no CloudSentinel": the agent keeps burning until a human notices, default 60 min);
for each TOOL_DENY/TIMEOUT, `saved = value_usd`; for TOOL_REWRITE, `saved = value_usd × (1 − new_amount/old_amount)`.
The brain fills `actions.usd_saved_estimate` with the same formula at action time.

**Cost → per-task success** (added 4 Nov): a task is one `invoke_agent` span. Every span with the same
`trace_id` (its chat, tool and graph_node children) is that task's cost. `success_rate` = succeeded / tasks;
`cost_per_success_usd` = the agent's spend / its successful tasks; `wasted_usd` = spend on failed or abandoned tasks
plus `unattributed_usd` (spans whose task hasn't finished, e.g. a graph stuck in a loop). Report-level
`cost_per_successful_task_usd` is fully loaded: all spend ÷ all successful tasks.

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

**Validation** *(added 8 Nov)* — every file is checked before it is allowed to replace the running policy.
The checks are explicit and pure Python (no new dependency). Each error names the exact path, so the
person who edited the file knows what to fix:

```
defaults.budget_usd: must be a number > 0
defaults.on_trip: must be one of pause, kill
tools[2].when.op: must be one of gt, gte, lt, lte, eq, ne, contains
tools[2].action: must be one of allow, deny, approval
agents.delta.budget_usd: must be a number > 0
```

**Hot reload** *(added 8 Nov)* — the brain checks the policy file's mtime every
`CS_POLICY_RELOAD_INTERVAL_SECONDS` (1 s). A change is loaded and validated; a **valid** file is
swapped in atomically and a `POLICY_RELOAD` action is recorded. An **invalid** file is rejected: the
last good policy stays in force and a critical `policy_invalid` alert carries the errors. The policy
in force is `GET /v1/policy`; `version` is `sha256(file)[:12]`.

### 11a. Prompt-injection and unsafe tool input *(added 8 Nov)*

Agent text is **data, never instructions** (AGENTS.md rule 8). `brain/injection.py` scores it two ways:

```python
score(text: str) -> tuple[float, list[str]]                       # 0..1, the reasons
score_tool_args(tool: str, args: dict) -> tuple[float, list[str]]  # 0..1, the reasons
```

Both return a `InjectionVerdict` (`{score, reasons, signals}`) — `score` is 0..1, `reasons` name the
signal that fired in plain English, `signals` are the signal names for counting.

**Text signals** — instruction-override (English + Bangla transliterations), system-prompt
exfiltration, role-play jailbreak markers, hidden text (zero-width characters, long base64 blobs),
memory poisoning ("always refund 100%").

**Tool-argument signals** — shell metacharacters in a tool that is not a shell, SQL like `; drop`,
path traversal, a URL to a host that is not on `CS_INJECTION_ALLOWED_HOSTS`, too many email recipients.

**Wiring**

| Where | Threshold | What happens |
|---|---|---|
| tool gate (`POST /v1/agents/{id}/tool-calls`) | score ≥ `CS_INJECTION_DENY_THRESHOLD` (0.8) | the call is **denied**; a `TOOL_INJECTION_DENY` action is recorded |
| tool gate | score ≥ `CS_INJECTION_APPROVAL_THRESHOLD` (0.5) and < 0.8 | the call goes **pending** for a human, with the reasons in `reason` |
| detectors (L5) | prompt score ≥ 0.8 | a `prompt_injection` finding for the judge |
| memory write (`PUT /v1/agents/{id}/memory`) | score ≥ `CS_INJECTION_MEMORY_THRESHOLD` (0.5) | an `injection_detected` alert (the write still happens — a human decides) |

The judge's `pattern` may now be `unsafe_tool_input` as well as `prompt_injection` (both added to
`shared.contracts.PATTERNS`).
