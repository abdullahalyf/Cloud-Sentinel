# HANDOFF: start here if you have no memory of earlier sessions

Written on Wed 4 Nov 2026 (the night before Day 1) by the lead session, for any fresh Codex / Antigravity / Claude session and for
every teammate. Read this file, then `AGENTS.md`, then your own `docs/tasks/<name>.md`. Never guess state from memory; the repo is
the truth.

**Project:** CloudSentinel, a circuit breaker + control tower for AI agents (hackathon: International AI Builders Congress 2026,
InfraSphere AI · AgentOps). Agents send OpenTelemetry spans → the brain detects loops, overspend and bad tool calls → a Claude judge
decides gray cases → the agent is paused, healed or killed from outside → the ROI engine prices it.
**Repo:** https://github.com/abdullahalyf/Cloud-Sentinel · default branch `main` · tests: `python -m pytest -q` (95 passed, 1 skipped on 4 Nov).

## 1. State of every layer

| Layer (owner) | Done ✅ | Partial 🟡 | Not started ⬜ |
|---|---|---|---|
| **Contracts** `shared/`, `docs/CONTRACTS.md` (Alif + Taseen) | Dataclasses, settings, pricing, `LocalStore` (SQLite WAL, auto-migrates), mock API with the same errors as the real one (`shared/mocks/`), contract + parity tests, `graph_node` spans + `spans.detail`, `/v1/agents/{id}/nodes`, per-task ROI keys | Open contract requests from Fojle (fojle.md, bottom) | Heal proposals, policy endpoints, workers table (Alif A3/A5/A8) |
| **Brain** `brain/` (Alif's agent) | Engine tick, state windows, hard limits, semantic-loop + tool-cycle detectors, breaker FSM (healthy → suspicious → paused → probation → healthy / killed), YAML policy + tool gate, judge (Claude / Gemini / fallback) hardened against agent text, C2 REST API + WebSocket, MCP server (destructive tools annotated), judge bench, SDK-enforced control for agents without a container | Prompt/threshold tuning was done **offline only** (fallback judge) | Labeled-incident eval, auto-heal, adaptive baselines, policy hot reload, injection detector, MCP packaging, sharding, E2E/chaos suite (A1–A9) |
| **Telemetry** `telemetry/` (Fojle) | SDK 0.3 (`init`, `llm_call`, `tool`, `task`, `node`, `gate`, `wait_if_paused`, `memory`), OTLP collector (JSON + protobuf), LangGraph adapter, CrewAI adapter, two demo agents, Phoenix export, rogue simulator (loop, paraphrase_loop, token_bomb, memory_leak, bad_tool_call) | `real_agent.py` has TODOs; `SupabaseStore` raises `NotImplementedError` (21 places) | Collector batching/backpressure, 4 new rogues, OpenAI Agents adapter, CloudWatch export, SDK docs, migrations |
| **Infra** `infra/`, compose, CI (Taseen) | `DockerExecutor` code, compose file (collector, brain, dashboard, 4 agents, optional Phoenix), Dockerfiles, CI jobs `test`, `adapters` (CrewAI venv), `compose`; nightly workflow | `docker-compose.scale.yml` is a v1 file (needs updating), Docker executor never tested against real containers | `K8sExecutor` (skeleton raises), Helm, socket proxy, secrets scan, folder guard, releases, public deploy, multi-node, Prometheus/Grafana, load test |
| **Dashboard** `dashboard/` (Tamjid) | Streamlit app: agent cards, token flow, approvals, memory editor (fallback from now on) | — | `docs/DESIGN.md`, the React + Vite web dashboard `dashboard/web/` (all panels, D1–D10) |
| **Eval** `eval/` (Orin) | `roi.py` (saved $, per-task cost → success rate, waste, cost per successful task), harness with 1 scenario (`paraphrase_loop`: 3 s / $2.25) | `eval/QA.md` is a stub | More scenarios, with-vs-without, RESULTS.md, deck, video script |
| **Docs** (Taseen) | DECISION (scope, 5-prompt pitch table §2b), ARCHITECTURE (incl. §7a web dashboard choice), CONTRACTS, PLAN (priorities + cut list), BRANCHING, research notes, task files | DECISION §6 "Winning Signal" is empty | DESIGN.md (Tamjid D1), ETHICS.md, PROVENANCE.md, NRB.md |

## 2. Verified live vs not

| Verified live ✅ (run for real, as separate processes) | Not verified ⚠️ |
|---|---|
| `python -m brain --fake`: beta's paraphrase loop is paused in ~3 s (harness) and the API serves the fleet | **The real Claude judge.** No `ANTHROPIC_API_KEY` reached the cloud session; only the fallback judge ran. Claude latency/cost numbers in `docs/research/judge-eval.md` are not measured yet |
| LangGraph refund agent + collector + brain: rogue → **paused 8 s later** between nodes → memory fix → resume → probation → healthy | **The hackathon site** (cloudcampbd.com) was blocked by the session's network: the deadline and the Winning Signal are unconfirmed |
| CrewAI crew: the 50,000 BDT refund was held, denied through the API, $409.84 recorded as saved | **Docker mode:** `docker compose up`, real `docker pause/kill` (no Docker daemon in the cloud session; only `docker compose config` ran in CI) |
| Arize Phoenix 21.0.0: all spans arrived as AGENT / CHAIN / LLM / TOOL | Supabase (no project yet), Kubernetes, MCP inside Claude Desktop, Windows laptops |
| CI on GitHub (`test`, `adapters`, `compose`): see the Actions tab after each merge | The nightly workflow (first run: the night of 5 Nov) |

## 3. Known bugs and risks
1. **Leaked Gemini key in git history.** Revoke it (Taseen H1). gitleaks will keep flagging the old commit, so allowlist that commit only after the key is revoked.
2. **CrewAI pins `mcp<2`; the brain needs `mcp>=2`.** Installing CrewAI into the main venv silently breaks `brain.mcp_server`. Keep it in `.venv-crewai` (§4).
3. **Fail-open SDK:** `cs.tool()` runs the tool if the brain is unreachable, unless `fail_closed=True`. The `bad_tool_call` simulator and `real_agent.py` don't set it yet (Fojle F11).
4. **Clock skew:** agents whose clock is > 60 s behind fall out of the loop window (Fojle F11 S2).
5. **Docker socket** is mounted into `brain`, which is root on the host. Use the socket proxy before any shared or cloud machine (Taseen T4).
6. **Branch protection is off** until Taseen H2. Alif's agent merges its own PRs, so CI is the only gate. Taseen reads its PRs daily.
7. **The mock and the real brain both use port 8000.** Never run both.
8. Semantic-loop false positives on busy healthy agents (risk R12): the `legit_burst` checks in A1/A2 and O7 guard this.
10. **One flaky test, not identified:** on 4 Nov one local `python -m pytest -q` run had 1 failure that didn't come back in 16 reruns (CI green).
    Suspects: the timing-based tests (`shared/tests/test_api_parity.py` node feed uses the wall clock; the LangGraph adapter tests use real threads).
    Alif's agent: reproduce with `for i in $(seq 30); do python -m pytest -q -rf | grep FAILED; done` in A10.
9. Running SQLite from several processes (A8 sharding) needs WAL plus busy_timeout. Don't point two brains at one DB file before A8.

## 4. Local setup on a normal laptop
**Needs:** Python **3.12** (3.11–3.13 work; CI uses 3.12), Git, and optionally Docker Desktop (Docker mode), Node **20** LTS (the web dashboard),
kind + kubectl + helm (K8s), and `gh` (the GitHub CLI, for Alif's agent loop).

```bash
git clone https://github.com/abdullahalyf/Cloud-Sentinel.git && cd Cloud-Sentinel
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -e "telemetry/sdk[langgraph]"
cp .env.example .env                                        # Windows: copy .env.example .env
python scripts/check_setup.py
python -m pytest -q                                         # expect: all passed, Docker tests skipped
```

**`.env` (never commit it):**
- Everything is optional; the defaults run fully offline.
- `ANTHROPIC_API_KEY`: the Claude judge (otherwise the fallback judge).
- `SUPABASE_URL` / `SUPABASE_KEY`: the shared DB (otherwise SQLite in `data/`).
- `CS_API_TOKEN`: required for any public deploy.
- `EXECUTOR=docker|k8s`.
- `CS_EXPORT_PHOENIX=true` + `PHOENIX_COLLECTOR_ENDPOINT`.
- The full list is in `docs/CONTRACTS.md` §3.

**Separate venvs (framework conflicts):**
```bash
python -m venv .venv-crewai && source .venv-crewai/bin/activate
pip install -e "telemetry/sdk[crewai]" fastapi httpx PyYAML pytest
CS_AGENT_ID=crew-support python telemetry/examples/crewai_support_crew.py      # the brain runs in the MAIN venv
```
Do the same for `openai-agents` if `pip check` shows a conflict (Fojle F7 S1).

**Run the demo (offline, no Docker):**
```bash
python -m brain --fake                # terminal 1: brain + API :8000 + 4 simulated agents; beta goes rogue after 20 s
streamlit run dashboard/app.py        # terminal 2: http://localhost:8501 (fallback dashboard)
cd dashboard/web && npm install && npm run dev   # terminal 2 instead, once Tamjid D2 is merged: http://localhost:5173
python scripts/demo.py fix beta && python scripts/demo.py resume beta   # heal beta
python scripts/demo.py reset
```
**A framework agent against the real brain:** add `python -m telemetry.collector` (terminal 3), then
`CS_AGENT_ID=lg-refund python telemetry/examples/langgraph_refund_agent.py --rogue-after 20`.
**Dashboard development without the brain:** `python -m shared.mocks.mock_api` (same port 8000).

**Docker:**
```bash
docker compose up -d --build                         # collector, brain, dashboard, 4 agent containers
python scripts/demo.py rogue beta paraphrase_loop    # docker ps shows beta (Paused)
docker compose --profile phoenix up -d               # optional: Arize Phoenix on :6006
docker compose down
```

**Tests:**
- `python -m pytest -q` runs the default suite.
- `python -m pytest -q -m "e2e or chaos"` runs the slow suites (nightly).
- `python -m eval.harness` runs the benchmark.
- `python -m brain.judge_bench` runs the judge benchmark.

## 5. Open decisions

| # | Decision | Default if nobody decides | Who |
|---|---|---|---|
| 1 | The real deadline and the Winning Signal text from the platform | PLAN.md dates (final submit Sun 15, 18:00 BST) | Taseen (H5) |
| 2 | Cloud provider for the public demo URL | The cheapest VM with free credit + Caddy (T9) | Taseen (H6) |
| 3 | Web dashboard vs Streamlit for the stage | Web, if D3–D5 are on `main` by CP2; otherwise Streamlit | Tamjid + Taseen at CP2 |
| 4 | Auto-heal default (on/off) for the live demo | On, with min confidence 0.85, and a human always sees the proposal | Alif's agent (A3) + Taseen |
| 5 | Does `openai-agents` need its own venv/CI job? | Decided by `pip check` in F7 S1 | Fojle |
| 6 | Branch protection: approvals for others' PRs (1) and bypass for Alif's agent | As in taseen.md H2 | Taseen |
| 7 | Judge model for the demo (cost vs latency) | `claude-haiku-5-5` until A12 measures the alternatives | Alif's agent (A12) |

## 6. The exact next 3 tasks for each person (task IDs are in `docs/tasks/<name>.md`)

| Person | Tool | 1 | 2 | 3 |
|---|---|---|---|---|
| **Taseen** | Antigravity | H1–H5: revoke the Gemini key, ruleset + bypass for Alif's agent, the Anthropic key as an Actions secret and in Alif's `.env`, Alif's laptop (`gh`, Codex full access), the platform deadline + Winning Signal | T1: gitleaks + folder-guard CI jobs | T2 + T3: `docker compose up`, the Docker executor against real containers |
| **Tamjid** | Antigravity | D1: `docs/DESIGN.md` (direction, tokens, components, anti-slop rules, review checklist) | D2: the `dashboard/web/` scaffold, typed API client, panel states, screenshot script | D3: fleet overview, then the daily screenshot review |
| **Fojle** | Codex | F1: setup + Supabase project + `schema.sql` | F2: SupabaseStore writes | F3: SupabaseStore reads + contract tests |
| **Orin** | Codex | O1: setup + watch the demo | O2: QA checklist (20 cases) | O3 + O4: ROI sentences, `eval/RESULTS.md` |
| **Alif** (agent) | Codex in VS Code (autonomous) | A0: Fojle's 3 open contract requests | A10: build `brain/nightly.py` | A1: labeled-incident judge eval (fallback now, Claude when the key is there) |

## 7. Where things are
- Rules for AI tools: `AGENTS.md` (Codex reads it automatically). Alif's loop: `AGENTS.md` → "Alif's agent loop".
- The data contract: `docs/CONTRACTS.md`. The mocks: `shared/mocks/README.md`.
- The plan, checkpoints and cut list: `docs/PLAN.md`. Branching: `docs/BRANCHING.md`. Pitch scope: `docs/DECISION.md`.
- Daily log in Bangla: `docs/SUMMARY_BN.md`. Group-chat brief: `docs/TEAM_BRIEF_BN.md`.
