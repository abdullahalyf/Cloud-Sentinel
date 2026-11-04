# Landscape: AgentOps tools, standards and frameworks (Nov 2026)

How to read this: for each tool we record **features → architecture → gaps**. The gaps are where
CloudSentinel can win. Sources: official docs and web searches on 2026-11-04, plus team knowledge.
Items marked *(unverified)* came only from secondary sources.

**The one-sentence finding:** the market is full of tools that *watch* agents (tracing, replay,
evals). Almost nobody *acts* on what they see, out of process and in real time: no circuit
breaker, no pause or quarantine, no memory edit, no tool-call override. The few "budget breaker"
libraries that do act all run **inside** the agent, so a broken agent can bypass them.

---

## 1. Standards

### OpenTelemetry + GenAI semantic conventions
- **Features:** a vendor-neutral standard for traces, metrics and logs. The `gen_ai.*` namespace
  defines spans for model calls (`chat`, `text_completion`, `embeddings`), **agent spans**
  (`create_agent`, `invoke_agent {gen_ai.agent.name}`) and **tool spans** (`execute_tool {gen_ai.tool.name}`).
  Key attributes: `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.agent.id`, `gen_ai.agent.name`,
  `gen_ai.conversation.id`, `gen_ai.tool.name`, `gen_ai.tool.call.id`, `error.type`.
  Metrics: `gen_ai.client.token.usage`, `gen_ai.client.operation.duration`.
- **Architecture:** SDK → OTLP exporter (gRPC on port 4317, HTTP on 4318) → Collector → any backend.
  A typical agent trace is `invoke_agent` → children `chat` / `execute_tool` / `chat` ….
- **Gaps:** the conventions are still **"Development" status** (≈v1.40–1.42 in 2026). In mid-2026
  the GenAI conventions moved into a separate repo *(unverified)*. Prompt and response content is
  opt-in and recorded as events. **OTel is one-way by design: it observes, it never controls.**
  There is no concept of "budget", "loop" or "kill".
- **Our use:** our SDK emits *exactly* these span names and attributes, and our collector accepts
  standard OTLP/HTTP. That means **any** OTel-instrumented agent (OpenLLMetry, LangChain, CrewAI)
  can be governed by CloudSentinel just by setting `OTEL_EXPORTER_OTLP_ENDPOINT`.

### MCP (Model Context Protocol)
- **Features:** JSON-RPC protocol between AI hosts (Claude Desktop, Claude Code, IDEs) and servers
  that expose **tools**, **resources** and **prompts**. Released spec versions: 2024-11-05,
  2025-03-26, 2025-06-18, 2025-11-25, **2026-07-28 (latest)**. The 2026-07-28 revision makes the
  core protocol **stateless** (each request carries its version and capabilities in `_meta`),
  removes `Mcp-Session-Id`, adds `server/discover`, and documents **OTel trace-context keys in
  `_meta`**. Transports: stdio and Streamable HTTP. OAuth-based authorization applies to HTTP.
- **Gaps:** MCP lets agents *call* tools, but nothing in the protocol *governs* those calls:
  no budgets, no approvals across a fleet, no audit trail. Every host implements its own
  "allow this tool?" prompt.
- **Our use:** (1) a **CloudSentinel MCP server**, so an operator can ask Claude "which agent is
  burning money? pause it", and (2) MCP tool calls inside agents go through our tool gate.
  The submission has an MCP disclosure section that "affects AgentOps/architecture scoring".

---

## 2. Observability platforms

### LangSmith (LangChain)
- **Features:** tracing, datasets, offline and **online evaluations** (LLM-as-judge, multi-turn,
  code evaluators on live traces), annotation queues, prompt hub, monitoring dashboards.
  **LangSmith Deployment** is the runtime for LangGraph agents (checkpoints, human-in-the-loop
  interrupts, cron, versioning and rollback). **Fleet** (formerly Agent Builder, renamed Mar 2026)
  is a no-code agent builder with agent identity, permissions, MCP and approvals *(partly unverified)*.
- **Architecture:** SaaS or self-hosted. The SDK sends runs to the LangSmith API. It accepts OTel too.
- **Gaps:** governance only works for agents built **and hosted** on LangGraph/LangSmith.
  There is no cross-framework kill switch, and the evals are about quality, not runaway cost.
  Enterprise pricing.

### LangChain LCEL tracing / callbacks
- **Features:** every Runnable in an LCEL chain emits callbacks (`on_llm_start`, `on_tool_start` …),
  and `astream_events` streams them. These are wired into LangSmith or OTel via
  `langchain-opentelemetry` / OpenLLMetry.
- **Gaps:** callbacks are **in-process and advisory**. A callback can raise an exception to stop a
  chain, but nothing coordinates this across processes, and there is no policy layer.
  It only covers LangChain code.

### Arize Phoenix
- **Features:** open-source (Elastic License 2.0) tracing UI built natively on OTel/OpenInference.
  Evals (LLM-as-judge templates for hallucination, relevance, toxicity), datasets and experiments,
  prompt playground, span annotations. Arize AX is the paid enterprise version.
- **Architecture:** a single container (`arizephoenix/phoenix`) with an OTLP receiver and an
  SQLite or Postgres store. Instrumentation is done with OpenInference auto-instrumentors.
- **Gaps:** offline and analytical, focused on debugging and eval quality. **No real-time
  enforcement or control actions.** No cost budgets per agent.
- **Lesson:** Phoenix shows that "OTLP in, one container, local-first" is a good developer
  experience. We copy that.

### AgentOps.ai
- **Features:** a Python SDK (`agentops.init()`) that auto-instruments CrewAI, AutoGen/AG2,
  LangChain, LangGraph, OpenAI Agents and more. **Session replay** / "time-travel" debugging,
  **cost tracking per session, agent and call (400+ models)**, error and loop views, benchmarks.
  Free tier, Pro around $40/mo *(unverified)*. The SDK is MIT-licensed.
- **Gaps:** **observe and replay after the fact.** It tells you *that* you burned $200,
  not stopping it at $5. It has no Docker/K8s awareness, no kill/pause, and no human override of tool calls.
- **Note:** they own the word "AgentOps". Our pitch must differentiate clearly: *"AgentOps.ai is
  the black-box recorder. CloudSentinel is the circuit breaker."*

### Helicone
- **Features:** an open-source LLM **proxy/gateway** (Rust AI Gateway): request logging, caching,
  retries and failover, **rate limits per user, team or global by requests, tokens or $**
  *(unverified)*, cost dashboards.
- **Architecture:** you change the base URL and all LLM traffic flows through the proxy.
- **Gaps:** **acquired by Mintlify in March 2026, reportedly in maintenance mode.** It sees LLM
  calls only: not tool calls, not memory, not containers. Its rate limits are blunt (HTTP 429)
  and cannot tell a loop from a legitimate burst.
- **Lesson:** the proxy position (outside the agent) is the right enforcement point. Helicone
  proved it, then stopped developing it, which leaves a gap for us.

### Weights & Biases Weave
- **Features:** `@weave.op` decorator tracing, automatic LLM-call capture, evaluations with
  scorers, leaderboards, a playground, guardrails/"scorers as guardrails", and cost tracking.
  W&B became part of CoreWeave in 2025.
- **Gaps:** ML-team centric, focused on evaluation and experiment comparison. Its guardrails are
  per-call content checks (toxicity, PII), **not fleet-level runtime control**.

### AWS CloudWatch Logs (+ CloudWatch GenAI observability / Bedrock AgentCore)
- **Features:** log ingestion, Logs Insights queries, metric filters → alarms → SNS/Lambda.
  The 2025–26 additions are GenAI observability dashboards for Bedrock AgentCore agents, with OTel (ADOT) ingest.
- **Gaps:** generic. You can *build* a kill switch (alarm → Lambda → stop task), but that takes
  minutes of latency and a lot of glue, and it **cannot judge intent** (loop or legitimate burst?).
  It is AWS-only.
- **Our use:** AWS is a Congress technology partner. Our stretch goal is a `cloudwatch` export
  sink, giving the story "runs on AWS ECS/EKS, alarms in CloudWatch".

### "ControlPlane" / agent control planes
- No single product called "ControlPlane" turned up in this category (controlplane.com is a
  general multi-cloud app platform). "Agent control plane" is now a **category term** used by
  Microsoft Foundry Control Plane, Guild.ai, Gravitee Agent Management, LangGuard, Drata and Lyzr.
- **Features (category):** agent registry and discovery, identity and permissions, policy
  enforcement at the gateway, audit trails, compliance reporting, trust scores.
- **Gaps:** enterprise-heavy, closed, tied to one cloud or gateway, with long sales cycles.
  None of them is something a small team or a Bangladeshi startup can self-host in 5 minutes.
  Runtime behavioural detection (loops, paraphrase loops, memory leaks) is mostly missing:
  they govern **who can call what**, not **whether this agent has gone crazy**.

### Small OSS "budget breakers" (direct competitors to our circuit breaker)
`breaker` (proxy, SIGKILL at $ budget), `AgentBudget` (SDK hard $ cap + loop detection),
`agent-cost-guardrails` (trip after N violations), `SteerPlane` (decorator cost ceiling +
tool allow/deny), `ai-loopguard` (pattern-based loop breaker), `circuitbreaker.dev`.
- **Common gaps:** single-process libraries, no dashboard, no fleet view, no human override,
  no AI judgment (exact-match or counter rules only), and no OTel. Most of them kill rather than pause or heal.
- **Takeaway:** the idea is validated (people are building it), but nobody has assembled the
  full product.

---

## 3. Evaluation

### Hugging Face leaderboards
- **Features:** the Open LLM Leaderboard (archived 2025), plus community leaderboards for agents
  and tools (e.g. GAIA, the Berkeley Function-Calling Leaderboard (BFCL), τ-bench-style tool-use
  boards, SWE-bench mirrors). They are Spaces backed by datasets and eval harnesses (lighteval).
- **Gaps:** they measure **model capability on static benchmarks**, not **operational
  reliability** of a deployed agent (does it loop? does it overspend? how fast do we detect it?).
  There is no benchmark for agent "runaway" failure modes.
- **Our use:** we publish a tiny **"Runaway Agent Benchmark"**: 7 scripted failure scenarios with
  detection precision and recall, false-kill rate, time-to-detect and $ saved. It is generated by
  `/eval` and can be shown as a leaderboard table comparing "rules only", "rules + Claude", and
  "no protection". That gives the judges an "evaluation methodology" item.

---

## 4. Agent frameworks (what our users build with)

### LangGraph
- **Features:** stateful graph of nodes and edges, **checkpointer** (persisted state per thread),
  `interrupt()` for human-in-the-loop, time-travel (edit state and resume from a checkpoint),
  `recursion_limit` (default 25) as a crude loop guard.
- **Gaps:** the recursion limit is a blunt step counter. It doesn't know about cost and doesn't
  catch paraphrase loops. Its human-in-the-loop requires the graph author to place interrupts
  ahead of time.
- **Lesson:** its "edit state, then resume" model is exactly what our **memory edit** feature
  offers, but **across any framework, decided at runtime by an operator**.

### CrewAI
- **Features:** role-based multi-agent "crews", tasks, processes (sequential or hierarchical),
  memory, tools, `max_iter` and `max_rpm` per agent, plus an enterprise control plane (CrewAI AMP)
  with tracing. OTel is available via instrumentors.
- **Gaps:** `max_iter`/`max_rpm` are static limits set in code. A crew stuck in a delegation
  ping-pong (A asks B, B asks A) is a classic failure that nothing detects semantically.

---

## 5. What the track's example prompts expect

| Prompt | What a strong answer looks like | Who covers it in the market today |
|---|---|---|
| P1 Token-flow dashboard showing recursive loops | Live per-agent token/min and $/min lines. A graph of agent → tool → model calls where **cycles light up**. Loop score over time | AgentOps (after the fact), Phoenix (traces). Nobody shows it live with cycles highlighted |
| P2 Circuit breaker | A real state machine (CLOSED → OPEN → HALF-OPEN), **hard rules plus intelligent judgment**, fail-safe, and graduated actions (warn → throttle → pause → kill) | Small OSS libraries, in-process only |
| P3 Command & Control API | REST plus MCP. **Edit memory** (and the agent continues with the new memory), **override tool calls** (approve, deny, rewrite arguments), pause and resume, every action audited | LangGraph (own agents only), enterprise control planes |
| P4 OTel telemetry library | `pip install`, 3 lines, GenAI semconv spans, works with any OTLP backend | OpenLLMetry, OpenInference, AgentOps SDK |
| P5 ROI attribution engine | $ per agent, per task, per successful outcome ("cost of pass"), and **$ saved by each intervention** with a clear formula | Cost dashboards exist. **Attribution of savings to interventions does not exist** |

---

## 6. Competitor gap table

✅ = yes · ◐ = partial / framework-locked / after the fact · ❌ = no

| Capability | LangSmith | Phoenix | AgentOps.ai | Helicone | W&B Weave | CloudWatch | Agent control planes (Foundry, Gravitee…) | OSS budget breakers | **CloudSentinel** |
|---|---|---|---|---|---|---|---|---|---|
| OTel GenAI-native ingest | ◐ | ✅ | ◐ | ❌ | ◐ | ✅ | ◐ | ❌ | ✅ |
| Live token/$ flow per agent | ◐ | ◐ | ◐ | ✅ | ◐ | ◐ | ◐ | ❌ | ✅ |
| Exact-repeat loop detection | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Paraphrase / semantic loop detection** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ | ✅ |
| Hard budget cap ($ / tokens) | ❌ | ❌ | ❌ | ◐ | ❌ | ◐ | ◐ | ✅ | ✅ |
| **AI judge for gray-zone cases** (LLM-as-judge *at runtime, to act*) | ◐ (evals only) | ◐ (evals only) | ❌ | ❌ | ◐ (evals only) | ❌ | ❌ | ❌ | ✅ |
| Enforcement **outside** the agent process (can't be bypassed) | ❌ | ❌ | ❌ | ✅ (LLM calls only) | ❌ | ◐ | ✅ | ◐ | ✅ |
| Container-level kill / **pause (quarantine)** / resume | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ (glue) | ❌ | ◐ (kill only) | ✅ |
| **Edit agent memory at runtime** | ◐ (LangGraph only) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Override / approve tool calls** (human-in-the-loop) | ◐ (LangGraph only) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ◐ (static allow/deny) | ✅ |
| MCP server for operators ("Claude, pause beta") | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ◐ | ❌ | ✅ |
| Prompt-injection-aware monitoring | ❌ | ◐ | ❌ | ❌ | ◐ | ❌ | ◐ | ❌ | ✅ |
| **ROI: $ saved attributed to each intervention** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Runaway-failure eval benchmark | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Framework-agnostic | ◐ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ | ✅ |
| Self-host in one `docker compose up`, works offline | ◐ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Status in 2026 | active | active | active | **maintenance** | active | active | enterprise | hobby | — |

**Where we deliberately do not compete:** prompt management, dataset curation, quality evals
(hallucination or relevance scoring), long-term trace storage and search. We **export** to
Phoenix or LangSmith via OTLP instead of rebuilding them. In the pitch: *"Keep your LangSmith.
Add CloudSentinel in front of it."*

## Sources
- OTel GenAI agent spans: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans
- GenAI semconv explainers: https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained ·
  https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
- MCP 2026-07-28 release: https://github.com/modelcontextprotocol/specification/releases/tag/2026-07-28 ·
  https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Helicone acquisition: https://mintlify-landing-page.vercel.app/blog/mintlify-acquires-helicone ·
  https://futureagi.com/blog/helicone-alternatives-2026/
- LangSmith Fleet: https://www.langchain.com/blog/introducing-langsmith-fleet ·
  https://blog.langchain.com/march-2026-langchain-newsletter
- AgentOps.ai: https://inference.net/content/agentops-alternatives/ · https://aitoolsatlas.ai/tools/agentops
- Agent control planes: https://learn.microsoft.com/azure/foundry/control-plane/overview ·
  https://www.drata.com/learn/agent-gov/agentic-control-plane · https://www.gravitee.io/control-plane-gate.html
- OSS breakers: https://github.com/gmaOCR/breaker · https://agentbudget.dev/ · https://circuitbreaker.dev/ ·
  https://github.com/obaijahjah/agentcost · https://dev.to/waxell/ai-agent-circuit-breakers-the-reliability-pattern-production-teams-are-missing-5bpg
