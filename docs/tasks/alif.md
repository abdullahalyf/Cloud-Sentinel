# Alif: Brain (`brain/`) + contracts co-owner (`shared/`): autonomous agent backlog

**This file is run by an AI coding agent (Codex in VS Code), not by a person.** Alif doesn't check, test, review or decide
anything here. The agent picks the next task itself, builds it, writes and runs its own acceptance tests, merges to `main`
when CI is green, marks the task done in this file, and logs 3 lines in Bangla to `docs/SUMMARY_BN.md`.
**How to run the loop:** `AGENTS.md` → section **"Alif's agent loop"**. A fresh Codex session with zero context starts there,
then reads `docs/HANDOFF.md`.

**Owns:** `brain/` · `shared/` and `docs/CONTRACTS.md`, `docs/ARCHITECTURE.md`, `telemetry/db/schema.sql`, `shared/mocks/` via `contract/…`
branches · this file · append-only `docs/SUMMARY_BN.md` · `docs/research/judge-eval.md` and new `docs/research/brain-*.md` ·
the "Notes" and "Contract requests" sections of other people's task files (notes only, never their code).
**Never edits:** `telemetry/` (except `schema.sql`), the `SupabaseStore` class, `dashboard/`, `eval/`, `infra/`, `.github/`, `docker-compose.yml`.
**Branches:** `alif/<task-id>-<slug>`, or `contract/<slug>` when `shared/` or CONTRACTS changes.
**Codex settings:** use the strongest available model with high reasoning effort for every task below. They're the hardest in the project.
**Needs a human? Never ask Alif.** Write the request under "Requests from Alif's agent" in `docs/tasks/taseen.md`, mark the
task `[!]`, and move on to the next task.

## Status legend (the agent edits these boxes)
`[ ]` todo · `[~]` in progress (branch, date) · `[x]` done (date, PR link) · `[!]` blocked (reason, who must act)

## Definition of done (every task)
1. The acceptance tests listed in the task are written **first**, then the code. Tests live in `brain/tests/` (or `shared/tests/` for contract work).
2. `python -m pytest -q` passes, plus the task's own extra commands.
3. `python -m eval.harness` still prints all ✅ (the harness is Orin's file, so don't edit it, but it must stay green).
4. Contract changes update **all** of: `shared/contracts.py`, `shared/config.py`, `telemetry/db/schema.sql` (with an `alter … if not exists`),
   `LocalStore` (+ `_migrate`), `shared/mocks/mock_api.py`, `docs/CONTRACTS.md`, the contract and parity tests, and `.env.example` for new settings.
   Then add one line under "Contract changes (for review)" in `docs/tasks/taseen.md`.
5. A PR to `main`. Every CI job must be green (`test`, `adapters`, `compose`, plus `secrets` and `folder-guard` once Taseen T1 adds them). Squash-merge, delete the branch.
6. This file: the box becomes `[x] (date, PR link)`. `docs/SUMMARY_BN.md` gets 3 Bangla lines. Both go in the same PR, before merging.

---

## 🔁 Recurring (check these at the start of every session)

### A0 · Contract-request inbox · 🔴 MUST · recurring
**Trigger:** any unchecked `- [ ]` line under a "## Contract requests" heading in `docs/tasks/*.md`.
> Prompt:
> *Read AGENTS.md, docs/CONTRACTS.md and docs/BRANCHING.md "Contract changes". Collect every unchecked item under "## Contract
> requests" in docs/tasks/*.md. For each group of related requests, create branch contract/<slug>. Implement it end to end (Definition
> of done, point 4). Keep every change additive: new fields have defaults, and old rows and old clients keep working. Never edit SupabaseStore
> (it's Fojle's). If a new table or column needs SupabaseStore code, write that to Fojle's "Notes" section. Tick each handled request as
> "[x] (PR link)" in the requester's file. Reject a request only if it breaks the contract or the offline rule, and write why next to it.*

**Acceptance (the agent writes and runs):** `shared/tests/test_contracts.py` and `shared/tests/test_api_parity.py` cover each new field,
setting or endpoint, and a LocalStore DB created before the change still opens (migration test).
**Open requests right now:** none (Fojle's 3 done in A0 run 1).
- [x] A0 run for 5 Nov (2026-11-04, https://github.com/abdullahalyf/Cloud-Sentinel/pull/22)

### A10 · [x] (alif/puku-a9-e2e-chaos-v2, 2026-11-08) Nightly integration check · 🔴 MUST · recurring (every session if the last nightly run failed or the last check was > 24 h ago)
> Prompt:
> *First time only: create brain/nightly.py (`python -m brain.nightly`). It runs, in order, and reports pass/fail plus a 30-line error
> tail for each step:
> 1. `python -m pytest -q`
> 2. `python -m pytest -q -m "e2e or chaos"` (exit code 5, "no tests", counts as a pass)
> 3. `python -m eval.harness`
> 4. `python -m brain.judge_bench --judge fallback`
> 5. a 20 s `python -m brain --fake` boot smoke that checks /v1/health and /v1/fleet
> 6. `docker compose config -q` (skipped without docker)
> 7. `cd dashboard/web && npm ci && npm test` (skipped without node or without the folder)
>
> It maps each failing test or step to its owner folder (by path) and writes data/nightly-report.md. The exit code is non-zero if anything
> failed.
> Every run: `git checkout main && git pull`, `gh run list --workflow nightly.yml -L 3`, read any open issue labelled
> "nightly" (`gh issue list -l nightly`), then run `python -m brain.nightly`. Fix failures in brain/ or shared/ on
> alif/nightly-fix-<date>. For failures in someone else's folder, DO NOT edit their code. Append to the "## Notes" section of their
> docs/tasks/<name>.md: the date, the failing command, the last 15 lines of the error, and the file you suspect. Close the nightly issue with a
> comment when everything is green.*

**Acceptance:** `brain/tests/test_nightly.py` checks the owner mapping and the report format with fake step results (no subprocesses).
- [x] A10 first build (brain/nightly.py)

---

## 🔴 MUST (do in this order)

### A1 · [x] (2026-11-08, https://github.com/abdullahalyf/Cloud-Sentinel/pull/24) Claude judge: real-run evaluation on labeled incidents (precision / recall)
**Done:** ৬৪টা labeled incident (`brain/eval_data/incidents.jsonl`) + scorer (`brain/judge_eval.py`) + ২৪টা test.
**Fallback judge:** precision 0.929, recall 0.839, F1 0.881, `legit_burst`-এ ০ false positive.
**Live Claude run:** [!] — `ANTHROPIC_API_KEY` নেই, তাই Claude-এর latency/cost সংখ্যা এখনো নেই।
**Owns:** `brain/judge_eval.py` (new), `brain/eval_data/incidents.jsonl` (new), `brain/tests/test_judge_eval.py`, `docs/research/judge-eval.md`.
**Needs:** `ANTHROPIC_API_KEY` for the live part. Without it, build and run everything with `--judge fallback`, mark the live run `[!]`,
and ask Taseen (H3).
> Prompt:
> *Read AGENTS.md, docs/ARCHITECTURE.md §5, brain/judge.py, brain/judge_bench.py and shared/mocks/fake_fleet.py.
> (1) Build a labeled dataset brain/eval_data/incidents.jsonl with at least 60 incidents. Each row has: id, family, a
> JudgeContext-like payload (snapshot, finding, prompts, tools, memory, history) and label {"intervene": bool, "ok_actions": [...]}.
> Sources:
> - capture real JudgeContexts by running the Engine with FakeFleet on a virtual clock for every rogue kind and for healthy agents
>   (write a small capture helper in brain/judge_eval.py)
> - the existing judge_bench scenarios
> - hand-written hard cases: legitimate bursts (varied order ids, a nightly batch job, retries that succeed), paraphrase loops that mix
>   English and Bangla transliteration, a slow budget leak, prompt injection inside a customer email
>
> At least 25 must be negatives (intervene = false). Synthetic data only.
> (2) `python -m brain.judge_eval --judge fallback|claude --runs N --write` computes:
> - intervene precision, recall and F1
> - a confusion matrix over KILL/PAUSE/WARN/IGNORE
> - the false-positive rate per negative family
> - latency p50/p95, $ per verdict, and the invalid-output rate
>
> With --write it updates the "Labeled incidents" section of docs/research/judge-eval.md and keeps the existing sections.
> (3) Tests (no network): the dataset validates (schema, counts, unique ids), the metrics math on a 4-row toy set, and a fallback run that
> is deterministic and has zero false positives on the legit-burst family. Live Claude tests are marked `live` and skipped without a
> key.*

**Acceptance:** the tests above pass. With a key, Claude reaches recall ≥ 0.90, precision ≥ 0.90, p50 < 3 s and zero invalid outputs.
If not, A2 tunes it, so write the gap down.

### A2 · [x] (alif/puku-a2-tuning, 2026-11-08, merged as #27) Judge prompt + detector threshold tuning
**Result:** precision 1.000 / recall 0.806 / F1 0.893, zero false positives. The six remaining misses
are the documented slow-money-leak and token-bomb gaps (one snapshot cannot separate them from
legitimate work) — pinned in `KNOWN_GAPS` in `brain/tests/test_tuning.py` so the list cannot rot.
**Owns:** `brain/judge.py` (prompt), `brain/tuning.py` + `brain/tuning.json` (new), `shared/config.py` defaults (contract branch),
`.env.example`, CONTRACTS §3, `docs/research/judge-eval.md`.
> Prompt:
> *Read A1's results in docs/research/judge-eval.md. (1) Write brain/tuning.py. It grid-searches LOOP_SCORE_THRESHOLD (0.45–0.8),
> BRAIN_KILL_CONFIDENCE (0.5–0.9), BRAIN_COOLDOWN_SECONDS (5–20) and the soft limits in shared/config.py by running the Engine with FakeFleet on a
> virtual clock for every rogue kind plus healthy and legit-burst traffic. The objective: zero false positives on the negatives first,
> then maximum recall, then minimum median time-to-detect. Write the winner and the full table to brain/tuning.json.
> (2) Prompt variants: the current one, plus few-shot (one paraphrase loop and one legit burst), plus an explicit evidence checklist.
> Run them through brain.judge_eval (Claude if a key is present, otherwise record "not run") and pick by F1, then cost.
> (3) Make the winning thresholds the defaults in shared/config.py, .env.example and CONTRACTS §3 (on a contract/ branch).
> (4) Add a regression test for every incident that was misjudged before tuning.*

**Acceptance:** `brain/tests/test_tuning.py` asserts that the defaults equal `tuning.json`'s winner, the regression tests pass, and the harness is all ✅.

### A3 · [x] (alif/puku-a3-autoheal, 2026-11-08) Auto-heal: the judge proposes a patch, high confidence applies it, otherwise it goes to the approvals inbox
**Owns:** `brain/heal.py` (new), `brain/judge.py`, `brain/engine.py`, `brain/service.py`, `brain/api.py`, `brain/mcp_server.py`, plus a contract
branch for the new table, endpoints and settings.
> Prompt:
> *Read AGENTS.md, docs/CONTRACTS.md §5–§7, brain/judge.py, brain/engine.py and brain/service.py.
> Contract (on contract/heal-proposals, first):
> - table heal_proposals (id, agent_id, created_at, verdict_id, kind "memory_patch"|"tool_policy", patch json, confidence,
>   status pending|applied|rejected|expired, decided_by, decided_at, reason)
> - GET /v1/heal-proposals?status= and POST /v1/heal-proposals/{id}/decision {decision: apply|reject, reason, requested_by}
> - action type AUTO_HEAL
> - settings CS_AUTOHEAL (default true) and CS_AUTOHEAL_MIN_CONFIDENCE (default 0.85)
> - MCP tool decide_heal (destructive)
> - mock parity, with one seeded pending proposal for beta
>
> Judge: the structured output gains an optional "patch":
> - {"memory": [{"op": "set"|"remove", "key": str, "value": any}]} (top-level keys only, max 5 ops, values ≤ 500 characters), or
> - {"tool_policy": {"tool": str, "action": "deny"|"approval"}}
>
> The fallback judge proposes a memory patch when the finding names a memory key (e.g. order_4471).
> heal.py validates a patch:
> - only keys that exist in the memory, or that the finding names
> - no instruction-like text (use brain/injection.py once A6 exists; until then, a small denylist)
> - never touches the "budget" keys
>
> Flow after a PAUSE verdict with a patch: if CS_AUTOHEAL and confidence ≥ min, then service.write_memory(actor "brain:autoheal",
> base_version=current) → RESUME → probation, and record an AUTO_HEAL action with the patch. Otherwise, create a pending proposal. A human (or
> MCP) apply runs the same path. Safety: at most one auto-heal per agent per 10 min. If the agent trips again during probation after
> an auto-heal, pause it and create a proposal (never auto-heal twice in a row). A proposal whose base_version is stale becomes expired.*

**Acceptance:** tests for
- high confidence → applied → the agent reaches healthy in a FakeFleet run
- low confidence → pending and nothing changed
- reject → it stays paused
- a re-trip → escalates to a human
- a stale version → expired
- an injection-like patch → refused
- mock/real parity
- the MCP tool

Write a note in `tamjid.md` (show proposals in the approvals inbox, kind "heal") and in `orin.md` (a harness scenario "auto-heal").

**Result:** `brain/heal.py` validates a patch (only existing or finding-named keys, never the budget
keys, never instruction-like text, ≤ 5 ops, values ≤ 500 chars) and applies it or files it as a
proposal. A confident patch (≥ `CS_AUTOHEAL_MIN_CONFIDENCE`, default 0.85) is written to the
memory, an `AUTO_HEAL` action is recorded and the agent is resumed on probation. Anything less
becomes a pending proposal; the human path runs the same code. A re-trip during probation after
an auto-heal pauses the agent (never kills it — the state the human needs survives) and files a
proposal. A stale `base_version` expires. The contract (table, endpoints, settings, mock parity)
landed as #28; the brain side is `alif/puku-a3-autoheal`. 38 acceptance tests in
`brain/tests/test_heal.py`. Notes written in `tamjid.md` and `orin.md`.

### A4 · [x] (alif/puku-a4-baselines, 2026-11-08, merged as #31 → 0923e0c) Adaptive per-agent baselines instead of fixed limits
**Owns:** `brain/baseline.py` (new), `brain/detectors.py`, `brain/engine.py`, plus a contract branch for `AgentView.baseline` and the settings.
> Prompt:
> *Read brain/detectors.py, brain/state.py and shared/config.py. For each agent, learn a robust baseline of tokens/min, usd/min, LLM calls/s,
> tool calls/s and the distinct-prompt ratio: a rolling median and MAD over the last 10 min of the agent's HEALTHY windows only (exclude
> suspicious/paused/probation). Warmup: the first CS_BASELINE_WARMUP_SECONDS (60) use the fixed soft limits. Adaptive soft limit =
> clamp(median + CS_BASELINE_K (4) × 1.4826 × MAD, floor = 0.25 × fixed soft limit, ceiling = fixed hard limit). Hard limits stay absolute.
> Persist baselines (a new json column agents.baseline, via the contract) so a brain restart keeps them. Expose AgentView.baseline
> {metric: {median, limit, samples}} so the dashboard can show "normal for this agent". The finding text says "3.4× above this agent's
> normal".*

**Acceptance:** tests for
- a stable high-usage agent (gamma-like analyst) never trips
- a 3× spike over its own baseline trips even when it's under the fixed limits
- warmup uses the fixed limits
- a restart restores the baseline
- legit_burst is not paused
- the harness is all ✅

**Result:** `brain/baseline.py` learns a rolling median and MAD over the last 10 minutes of an
agent's **healthy** windows only (a suspicious, paused, probation or killed agent is not normal,
so it never teaches the brain a new normal). The adaptive soft limit is
`median + CS_BASELINE_K (4) × 1.4826 × MAD`, clamped between a quarter of the fixed soft limit
and the fixed hard limit — the hard limits stay absolute. Two additions the tests forced:
the MAD is floored at a fraction of the median (a perfectly stable agent has MAD 0, and a limit
of exactly its median would trip on its own jitter), and the rate metric `calls_per_sec` gets a
wider floor because it arrives in bursts. The detector takes the baseline as an argument and the
finding says "3.4× above this agent's normal". The engine learns during the warmup but does not
*use* the baseline until `CS_BASELINE_WARMUP_SECONDS` (60) has passed — until then the fixed soft
limits decide. The learned limits live in `agents.baseline` (contract #30), so a brain restart
keeps them; the engine restores them from the store at startup. The contract side landed as #30
(`agents.baseline`, `AgentView.baseline`, `CS_BASELINE_*`, and a store that keeps a baseline when
the agent row is written again — the brain upserts it every tick, so a blind upsert would wipe it).
18 acceptance tests in `brain/tests/test_baseline.py`, plus an API test that the fleet carries the
baseline. The harness is still all ✅.

### A5 · [x] (alif/puku-a5-policy-reload, 2026-11-08) Policy-as-code with hot reload
**Owns:** `brain/policy.py`, `brain/policy_schema.py` (new, pure Python), `brain/api.py`, `brain/mcp_server.py`, plus a contract branch for the endpoints and `CS_POLICY_FILE`.
> Prompt:
> *Read brain/policy.py, brain/policies.yaml and CONTRACTS §11.
> - Validate the policy file with explicit pure-Python checks (no new dependencies), giving errors with the path ("tools[2].when.op: must be
>   one of gt, lt, eq, contains").
> - Each tick, check the file's mtime (cheap). On a change, load and validate it. If it's valid, swap it in atomically, give it version =
>   sha256[:12], and record a POLICY_RELOAD action with a one-line diff summary. If it's invalid, keep the last good policy and write a
>   critical alert "policy_invalid" with the errors.
> - Endpoints (contract): GET /v1/policy {version, loaded_at, source, defaults, agents, tools, last_error}, POST /v1/policy/reload, and POST
>   /v1/policy/validate (YAML text in, errors out).
> - MCP: get_policy (read-only) and validate_policy.
> - Mock parity.*

**Acceptance:**
- Editing `policies.yaml` changes a tool-gate decision within 2 ticks, without a restart.
- Broken YAML → the old policy is still enforced, plus the alert.
- The validate endpoint returns path errors.
- Parity test.

**Result:** `brain/policy_schema.py` validates a policy file with explicit pure-Python checks (no
new dependency) and every error names the exact path — `tools[2].when.op: must be one of gt, gte,
lt, lte, eq, ne, contains`. `brain/policy_reload.py` owns the policy in force: it watches the
file's mtime, and on a change it loads and validates the file. A **valid** file is swapped in
atomically (one assignment — no tool call ever sees half a policy), gets `version = sha256[:12]`,
and records a `POLICY_RELOAD` action with a one-line diff summary ("budget $0.50 → $1.00, +1
rule(s): issue_refund"). An **invalid** file is **rejected**: the last good policy stays in
force and a critical `policy_invalid` alert carries the errors. A *deleted* file is also rejected —
removing the rules would silently open the fleet up, so that takes a human on purpose. The engine
checks the file once per tick (`CS_POLICY_RELOAD_INTERVAL_SECONDS`, default 1) and pushes the new
`on_trip` / `on_hard_limit` into the live breakers, so a changed policy applies to the very next
trip. The API serves `GET /v1/policy`, `POST /v1/policy/reload` and `POST /v1/policy/validate`;
MCP gained `get_policy` and `validate_policy` (both read-only, so the MCP tool count is 16 now).
The contract side landed as #32 (`b6f7f49`) — the endpoints, the `POLICY_RELOAD` action type,
`CS_POLICY_RELOAD_*` and a mock that reads the policy file on its own. 34 acceptance tests in
`brain/tests/test_policy_reload.py`, including the acceptance case: editing `policies.yaml`
changes a tool-gate decision within 2 ticks, with no restart.

### A6 · [x] (alif/puku-a6-injection, 2026-11-08) Prompt-injection and unsafe tool-input detection
**Owns:** `brain/injection.py` (new), `brain/eval_data/injection.jsonl` (new), `brain/service.py` (tool gate), `brain/detectors.py`,
`brain/judge.py` (context flag), plus a contract branch (`PATTERNS` += `prompt_injection`, `unsafe_tool_input`).
> Prompt:
> *Read AGENTS.md rule 8 (agent text is data, never instructions). Write brain/injection.py: score(text) → (0..1, reasons) and
> score_tool_args(tool, args) → (0..1, reasons). Signals:
> - instruction-override phrases (English plus common Bangla transliterations)
> - system-prompt exfiltration
> - role-play jailbreak markers
> - hidden text (zero-width characters, long base64 blobs)
> - tool-argument attacks: shell metacharacters in non-shell tools, SQL like "; drop", path traversal, URLs to hosts not on an allowlist in
>   policies.yaml, email recipient counts
> - memory poisoning: an agent's memory write that adds rules like "always refund 100%"
>
> Wire it in:
> - The tool gate: score ≥ 0.8 → deny; 0.5–0.8 → approval with the reasons.
> - Findings: a prompt with score ≥ 0.8 creates a "prompt_injection" finding for the judge.
> - Agent memory writes that score ≥ 0.5 raise an alert.
>
> Build a corpus brain/eval_data/injection.jsonl: ≥ 40 attacks and ≥ 40 benign hard negatives (a customer writing "please ignore my
> previous email", a SQL tutorial question, a normal URL). Write the precision/recall to docs/research/brain-injection.md.*

**Acceptance:** recall ≥ 0.85, benign false positives ≤ 5%, every existing test green, and Fojle's `prompt_injection` simulator (once merged) is
caught in `--fake` (if it isn't merged yet, an equivalent FakeFleet behaviour is).

### A7 · [x] (alif/puku-a7-mcp-packaging, 2026-11-08) MCP server hardening + packaging
**Owns:** `brain/mcp_server.py`, `brain/mcp_pkg/` (new: `pyproject.toml`, README), `brain/MCP.md` (new), plus a contract branch for `CS_MCP_READONLY`.
> Prompt:
> *Read brain/mcp_server.py and CONTRACTS §7.
> Hardening:
> - Validate every tool input: the agent id exists (via the API), string lengths, enums. Return clear error text, never a stack trace.
> - A per-session rate limit (30 destructive calls/min).
> - --http mode refuses to start on a non-localhost bind unless settings.api_token is set, and then requires "Authorization: Bearer
>   <token>".
> - CS_MCP_READONLY=true exposes only read tools.
> - Audit every tool's readOnlyHint/destructiveHint.
> - Add resources cloudsentinel://fleet and cloudsentinel://agents/{id}, and a prompt "triage_fleet".
>
> Packaging: brain/mcp_pkg/pyproject.toml builds a "cloudsentinel-mcp" package with a console script cloudsentinel-mcp. The server
> must only need httpx + mcp at runtime (move its settings reading into a tiny local helper that reads the same env vars, so the
> package doesn't import shared/). brain/MCP.md has the Claude Desktop, Claude Code and Codex config snippets.*

**Acceptance:**
- In a fresh venv, `pip install ./brain/mcp_pkg && cloudsentinel-mcp --help` works (a test that builds the wheel with `pip wheel`).
- An in-process stdio client lists the tools and calls `list_agents` against the mock.
- Tests for the token requirement, read-only mode and the rate limit.

**Done.** One implementation, in `brain/mcp_pkg/cloudsentinel_mcp/` — it needs only `httpx` and `mcp`
at runtime and does not import `shared/`, so it installs on its own. `brain/mcp_server.py` is now a
thin wrapper over it, so `python -m brain.mcp_server` and the installed `cloudsentinel-mcp` behave
identically and there is only one server to keep hardened. Every argument is validated before it
reaches the API (the error type subclasses the SDK's `ToolError` on purpose — the SDK only passes
the *message* of an anticipated `ToolError` to the model). Destructive calls are rate limited per
session, reads are never throttled. `CS_MCP_READONLY=true` hides every write tool. `--http` on a
non-localhost bind refuses to start without `CS_API_TOKEN`. Every tool declares `readOnlyHint` and
`destructiveHint`, and a test fails a tool that is in neither set — an un-audited tool cannot ship.
The contract side landed as #36 (`f81dc2b`) — `CS_MCP_READONLY`, `CS_MCP_RATE_LIMIT`,
`CS_MCP_HTTP_HOST`, `CS_MCP_HTTP_PORT`, and the safety rules written into CONTRACTS §7 as contract
rather than implementation detail. 36 acceptance tests in `brain/tests/test_mcp_hardening.py`,
plus 9 in `shared/tests/test_mcp_contract.py` (the two that compare the repo against the packaged
server skip until the package is in the tree — they are the ones that catch the two readers
drifting apart). `brain/MCP.md` has the Claude Desktop, Claude Code and Codex snippets.

### A8 · [x] (alif/puku-a8-sharding, 2026-11-08) Horizontal scaling: shard agents across brain workers
**Owns:** `brain/sharding.py` (new), `brain/engine.py`, `brain/__main__.py`, plus a contract branch for the `workers` table, `CS_WORKER_ID` and the health fields.
> Prompt:
> *Goal: N brain worker processes share the fleet, and one dies → the others take its agents within 15 s.
> - Each worker heartbeats every 2 s into a new table workers (worker_id, started_at, last_seen, agents_owned).
> - Owner of an agent = rendezvous hashing (highest sha1(agent_id + worker_id)) over workers seen in the last 10 s. Never use Python's hash().
> - Each Engine only ticks, judges and executes commands for the agents it owns.
> - `python -m brain --worker` runs an engine without the API. `python -m brain` stays API + one worker. `--fake` stays single-process.
> - /v1/health lists the workers and their agent counts.
> - SQLite: WAL plus busy_timeout 5000 so several processes can share the file.*

**Acceptance:**
- 2 Engine instances on one LocalStore file with 50 FakeFleet agents: every agent is owned by exactly one.
- Stopping one → full takeover in ≤ 15 s (virtual clock).
- No command runs twice.
- Tick p95 < 200 ms per worker at 50 agents.
- Numbers go in `docs/research/brain-scaling.md`. Note Taseen's T13 load test in `taseen.md`.

**Done.** `brain/sharding.py` (rendezvous hashing, the `Shard`, the heartbeat, the takeover) + the
engine's `owns()`/`_reshard()` + `python -m brain --worker [--worker-id]`. The contract side is
`workers` table + `CS_WORKER_ID`/`CS_WORKER_HEARTBEAT_SECONDS`/`CS_WORKER_STALE_SECONDS` + the health
fields (PR #38) and the one-sided parity rule (PR #39). 30 tests in `brain/tests/test_sharding.py`.

Measured: split 24/26 of 50, takeover **12.0 s** (budget 15), tick p95 **194 ms** (budget 200),
commands run once. Numbers and the profile in `docs/research/brain-scaling.md`.

The tick is close to the line: `sqlite3.Connection.commit` is 64% of it, because `LocalStore`
commits once per write and the brain writes two rows per agent per tick. The fix is a batched write
in `shared/store.py` (Fojle's folder) — noted in `docs/tasks/fojle.md`.

### A9 · [x] (alif/puku-a9-e2e-chaos, 2026-11-08) Full-stack E2E + chaos suite (runs nightly in CI)
**Owns:** `brain/tests/e2e/`, `brain/tests/chaos/` (new). The nightly workflow `.github/workflows/nightly.yml` already exists and runs
`-m "e2e or chaos"`. Only Taseen edits it: if it needs a change, ask under "Requests from Alif's agent" in taseen.md.
> Prompt:
> *Write pytest tests marked @pytest.mark.e2e. Each starts real processes on free ports with a temp data dir: `python -m brain --fake`,
> `python -m telemetry.collector`, and `telemetry/examples/langgraph_refund_agent.py` (skip if langgraph isn't installed). Kill every
> process at the end, even on failure. Scenarios:
> - the paraphrase loop → paused in ≤ 15 s
> - fix memory + resume → healthy in ≤ 45 s
> - the token bomb → killed
> - a 50,000 refund held → deny → $ saved > 0
> - MCP stdio list_agents works
> - lg-refund is paused between nodes
>
> Then tests marked @pytest.mark.chaos:
> - the executor raises 30% of the time
> - the SQLite DB is write-locked by another connection for 3 s
> - the judge sleeps past its timeout
> - the collector is killed and restarted mid-run
> - a burst of 50 spans/s
> - malformed OTLP
> - an agent clock 2 min behind
>
> In every chaos test the engine never dies, no agent disappears from /v1/fleet, tick p95 < 200 ms, and the right alerts are written.
> The whole suite must finish in < 6 min.*

**Acceptance:** `python -m pytest -q -m "e2e or chaos"` is green locally, and the nightly workflow is green on its next run.

**Done.** 11 E2E tests and 14 chaos tests, green, in **2m13s** (budget 6 min). The nightly workflow already ran
`-m "e2e or chaos or perf"` and installed the langgraph extra — **no change was needed**, so nothing was asked of Taseen.

The E2E suite drives the real thing: a real brain process, a real collector, a real LangGraph agent, on free ports
with a temp database, killed afterwards however the test ended. The harness is `brain/tests/e2e_harness.py`, not
`brain/tests/e2e/conftest.py` — two conftests with the same module name in two non-package directories means pytest
loads the first and silently ignores the second, and every test failed with "fixture 'harness' not found".

**The chaos suite found two real bugs, both fixed here:**

1. **A throwing executor killed the tick.** `_apply` called the runtime directly, so a raised exception escaped
   instead of becoming an alert — and it escaped at the exact moment the runtime broke, which is the moment the brain
   most needs to be watching. A silently failed pause is the worst outcome of all: the brain believes the agent is
   stopped, and it is running. Now the exception is caught, alerted as `executor_failed`, and the action is still
   audited. (`brain/engine.py`)
2. **A locked database stalled the brain for 3.9 s per tick.** The store's busy timeout is 5 s — generous, so a second
   worker waits rather than fails — but the brain writes two rows per agent, four agents is eight writes, and 5 s × 8
   is a brain that goes silent for a minute. The brain now shortens the timeout on *its own* connection to 50 ms
   (`brain/__main__.py`): a collision costs one skipped write, which the next tick writes again. The store's own
   default is unchanged for everything else. The p95 under a lock went from **3914 ms to under 200 ms**.

The engine now also logs how long each tick took (`tick took N ms`), so the brain's own log is the honest record of
the loop's health.

**For Fojle:** the busy timeout in `shared/store.py` is still 5 s for everyone else. A `CS_STORE_BUSY_TIMEOUT_MS`
knob would let the store's own users shorten it too. Noted in `docs/tasks/fojle.md`.

---

### A10 · [x] (alif/puku-a9-e2e-chaos-v2, 2026-11-08) Nightly integration check
**Owns:** `brain/nightly.py` (new), `brain/tests/test_nightly.py` (new).

**Done.** `python -m brain.nightly` runs the seven steps in order and writes `data/nightly-report.md`. The report is a
checklist — a table of step, status, time, owner and detail — and each failure carries the last 30 lines of its output
and the name of the person who owns the folder it broke in. The exit code is non-zero if anything failed.

**The owner mapping is the point.** The repo is split into folders and each folder belongs to one person, so a failure
in `telemetry/` is Fojle's and a failure in `dashboard/` is Tamjid's. The report says which, so the right person reads
it and the nightly agent never edits somebody else's folder. `shared/store.py` is the one exception that breaks the
rule — it is Fojle's even though it sits in `shared/`, which is the contract's — and the mapping says so.

**Skips are not failures.** No Docker, no Node, no `dashboard/web/` — those steps are skipped and marked as such,
because a machine without Docker is not a broken product, and a report full of skips nobody can fix trains people to
ignore the report. A skipped step is *not run at all*; running it anyway would turn the skip into a failure and cry
wolf about a machine that is fine.

**Two things the Windows console taught us.** The default code page there is cp1252, which cannot encode `→` or a check
mark, so the console output is plain ASCII (`[ok]`, `[FAIL]`, `[skip]`) while the markdown report keeps the Unicode
marks. And `shutil.which("npm")` finds `npm.CMD`, which `CreateProcess` cannot exec, so a missing tool can be a
`FileNotFoundError` even when it is installed — a step that cannot start is reported with the reason, not as a
mystery.

**The nightly already earned its keep.** On its first full run it caught the flaky wall-clock test
(`test_the_tick_is_fast_at_fifty_agents`, 208 ms against a 200 ms budget) that passes in isolation — a loaded-machine
artifact that the unit suite had been hiding, and that the nightly will now report every night until the perf work in
A11 makes it honest.

**Re-run 2026-11-08 12:44 — all green.** The recurring trigger fired (the last run had failed), so the nightly was
re-run: `unit` ✅ 28 s, `e2e + chaos` ✅ 123 s, `eval harness` ✅, `judge bench (fallback)` ✅, `boot smoke` ✅,
`docker compose config` ✅, `dashboard tests` ⏭️ skipped. The `unit` step that failed last time is the flaky
wall-clock p95 test from A11, and A11's own work is what made it pass: the tick at 50 agents now runs in ~13 ms
against a 200 ms budget, so the old 208 ms cliff is gone. The report says **"Result: ✅ all green"**.

36 tests in `brain/tests/test_nightly.py`, no subprocesses: the owner mapping (over 13 paths, both separators), the
suspect-file extraction (a pytest failure, a traceback, a path that does not exist, output that points at nothing),
the report format (says what failed, shows the owner, shows the last 30 lines and not the head), and the steps
themselves.

---

## 🟡 SHOULD

### A11 · [x] (alif/puku-a9-e2e-chaos-v2, 2026-11-08) Engine performance at 100 agents
Profile `tick()` with 100 FakeFleet agents (cProfile). Make the loop similarity incremental (cache shingles per prompt hash, compare only new
prompts) and batch the store reads. **Acceptance:** tick p95 < 200 ms at 100 agents, a test with a timing budget (marked `perf`, run nightly), and
`docs/research/brain-perf.md`.

**Done.** Tick p95 at 100 agents: **513 ms → 13.2 ms** (budget 200 ms). The profile named both
culprits and neither of them was the brain doing its job.

**84% of the tick was `sqlite3.Connection.commit`.** The tick writes two rows per agent and the
store commits after each one, so 100 agents = 200 disk syncs per tick. `brain/write_batch.py`
collects the tick's rows and writes them in one transaction, on the store's own connection, under
the store's own lock. Commits per tick: 200 → 1. It is in the brain and not the store because the
store cannot know that the rows it is handed all belong to one tick — only the brain knows that —
so `shared/store.py` did not change at all.

**The second cost was re-doing work whose answer was known.** `semantic_loop_score` re-tokenized
and re-clustered all 16 recent prompts every tick, for every agent, but the window slides by one
prompt at a time — 15 of the 16 word sets are unchanged. `loops.IncrementalLoopScore` keeps the
clusters between calls and places only the new prompt. And `score_text` was called on the same 12
prompts twice per tick (once for the count, once for the maximum), so `AgentWindow` now caches it
by the text. `re.Pattern.search`: 32,256 calls → 945.

**The one thing the fast path must not get wrong.** The loop score is what the detectors act on,
so it has to be the *same number* the plain scorer gives. The greedy clustering is order-dependent,
so the fast path only runs when the new window is a suffix-extension of the old one; anything else
falls back to recomputing. `brain/tests/test_perf.py` checks the two agree prompt for prompt, as
the window slides, as it shrinks, and after a mid-window change.

**The three rules a batch must not break**, each one a test: the same rows are written; a learned
baseline survives (an empty baseline means "no new baseline" — and in a batch one agent may have a
baseline and another may not, which a single upsert cannot express); and a failed batch loses
nothing, because the rows are then written one at a time exactly as before.

Scaling curve (one worker, one store, 20 ticks after 3 warm-ups): 10 agents 4.1 ms p95, 25 → 6.9,
50 → 8.2, **100 → 13.2**, 200 → 25.1. Close to linear with a small constant.

**For Fojle:** the A8 bulk-write request is now solved on the brain's side, so it is only worth
having in the store for the *other* users — a `store.transaction()` context manager would let any
caller batch and would be a nicer API than the brain reaching into `store._conn`. Noted in
`docs/tasks/fojle.md`, with the rule about baselines that a general version has to keep.

### A12 · [x] (alif/puku-a12-judge-cost, 2026-11-08) · Judge v2: cost cap + model comparison
- An hourly judge spend cap (`CS_JUDGE_MAX_USD_PER_HOUR`, contract). Above it, use the fallback and write an alert.
- Bangla/English mixed prompts in the dataset.
- Run brain.judge_eval for the fallback and for every Claude model available to the key (and Gemini if a key exists).
- Write an accuracy vs latency vs cost table to `docs/research/judge-eval.md` for Orin's slide (O16).

**Acceptance:** a cap test with a fake clock, and the table exists, with "not run" where no key was available.

**Done.** The contract side (`CS_JUDGE_MAX_USD_PER_HOUR`) merged first as PR #44, so the brain
branch rebased cleanly onto it.

**The cap.** `brain/judge_spend.py` is a new file: a rolling-hour spend tracker with an injected
clock. The judge stops calling the LLM above the cap, falls back to the deterministic judge, and
the engine writes a `judge_cost_capped` alert (once per agent, so forty agents do not bury the
dashboard). Two decisions worth stating:

- **Rolling hour, not clock hour.** A window that starts at the top of the wall-clock hour would
  let a fleet spend the whole cap in the first minute and judge nothing for 59 minutes.
- **The clock is injected.** The engine already runs on a virtual clock in the tests; a cap
  measured against a *different* clock than the one that produced the events is a cap nobody can
  trust. `brain/tests/test_judge_cost.py` — 18 tests, all offline, no key needed.

**The mixed-language family.** Six new cases (3 positives, 3 negatives) in a family of their own,
so the false-positive rate for a Bangla/English fleet is measured on its own instead of being
averaged into `paraphrase_loop`. One case is written in the Bangla *script*, not transliteration —
the word overlap with the English cases is zero. The negatives are the important half: a naive
word-overlap detector stops the Bangla support desk. The fallback gets all six right (3 PAUSE,
3 WARN, **zero** false positives).

**The table.** `docs/research/judge-eval.md` now has the accuracy-vs-latency-vs-cost table for
Orin's slide (O16). **Only the fallback row is measured** — this machine has no key for any
model (the `.env` is the untouched `.env.example` template), so the five LLM rows say "not run"
instead of carrying invented numbers, and the file has the exact commands to fill them in.

The dataset grew 64 → **70** incidents (34 positives, 36 negatives, 18 families). The fallback's
measured score: precision **1.000**, recall 0.824, F1 0.903, false-positive rate **0.000**.
Recall is still below the 0.90 target for the reason A1 documented — the slow money leaks come
back WARN, because on their own they look exactly like legitimate heavy work, and only the LLM
judge (which reads the logs) can tell them apart.

**Needs Alif:** a real `ANTHROPIC_API_KEY` (and `GEMINI_API_KEY`) to fill in the five `not run`
rows. One command per row, ≈ $0.03 on Haiku for all 70 × 3 runs — it is not a money decision, it
is a "somebody has to paste a key" one. The commands are in the doc.

### A13 · [x] (alif/puku-a13-explain, 2026-11-08) · Incident explanation endpoint
Add `GET /v1/agents/{id}/explain?minutes=10` (contract): a deterministic summary of what happened (alerts → verdict → action → heal), with
an optional Claude polish when a key is present. Add MCP tool `explain_agent`. **Acceptance:** parity test, and a golden-text test for the fallback.

**Done.** The contract side merged first (PR #46, `c6a8ae5`), so the brain branch rebased cleanly onto it.

**The text is written once.** The paragraph and the event shape live in `shared/contracts.py`
(`explain_event` / `explain_summary` / `explain_report`), and the mock and the real API both call
them. If the words were written twice — once in `shared/mocks/` and once in `brain/` — the two would
drift, and the golden test would be testing the mock against itself.

**The story is built in the brain's own layer.** `brain/explain.py` collects the four kinds of event
(alert → verdict → action → heal), filters them by agent and by window, and sorts them by **the time
they happened**, not by the table they came from: an alert that came after a verdict cannot have
caused it. `shared/store.py` is Fojle's folder, so the filtering happens here rather than by asking
for new store methods — `recent_alerts` and `recent_actions` have no agent filter, so the rows are
narrowed in the brain.

**The summary is deterministic.** No key, no network, no clock of its own: the same agent and the
same store always produce the same words. That is what makes it testable (a golden-text test pins
the exact sentences) and safe to cache. The Claude polish is layered on top and can only ever *add*
the `polished_summary` field — it can never make the endpoint fail, and a rewrite that drops a number
("$0.2500" → "a little") is rejected rather than shown, because a fluent sentence that says something
subtly different from what happened is worse than no sentence at all.

**Two things worth stating:**

- **An unknown agent is a 404**, the way the mock answers it. An explanation of nothing would be a
  confident paragraph about an agent nobody has ever heard of.
- **The window is a real window.** `?minutes=10` excludes an alert from two hours ago; `?minutes=180`
  brings it back. It is clamped to 24 hours, because a window of "forever" is not a window.

**`brain/tests/test_explain.py`** — 18 tests: the endpoint's shape, the 404, the golden text of a
story, the golden text of an agent with nothing to report, the outcome, the event order, the counts,
another agent's events staying out of the story, the window in both directions, the clamp, the parity
with the mock, and the three ways the polish can fail.

### A14 · [x] (alif/puku-a14-tool-risk, 2026-11-08) · The learned tool risk
Add `GET /v1/tool-risk?agent_id=` (contract): what a human has approved, per (agent, tool, args) —
auto-approve after 5 human approvals of the identical call, with an audit trail. Add MCP tool
`get_tool_risk`. **Acceptance:** a deny is never learned away, and a parity test.

**Done.** The contract side merged first (PR #50, `b4c6d9f`), so the brain branch rebased cleanly onto it.

**The counting rule is written once.** `tool_risk_from_history` lives in `shared/contracts.py`, and
the mock and the real API both call it. If the rule were written twice — once in `shared/mocks/` and
once in `brain/` — the two would drift on the one question that matters here: *what counts as an
approval?* The mock's history is the same history the real API reads, scored by the same function.

**Only a human answer teaches the brain.** A `policy` allow is the rules doing their job; an `mcp`
answer is another agent's opinion. Neither is a person saying "yes, this is fine", so neither may
teach the brain to stop asking. A pending call teaches nothing, and a rewritten call was not
approved as it stands.

**A denial is a veto.** A call a human refused is never auto-approved, however many times somebody
else later said yes. The counts stay visible — five approvals and one denial is still five
approvals and one denial — because an operator has to be able to see *both* before trusting the
number.

**The learned score never loosens a deny.** The auto-approval is checked only on the `approval`
path, after the policy rules have already run, so a deny rule, a paused agent and an injection
denial are all untouched by the learning. A store that cannot be read is not learning either: it
fails safe, with no auto-approval.

**The audit trail.** Every auto-approval writes a `TOOL_AUTO_ALLOW` action by the `brain:toolrisk`
actor, so an operator can see which calls went through on their own and on what evidence.

**`brain/tests/test_tool_risk.py`** — 22 tests: the fifth approval teaching the brain, the
auto-approval in the audit log, the denial vetoing the learning, a policy allow not teaching, a
deny rule never being learned away, a paused agent getting no tools even when learned, an injection
being denied even when learned, the real API and the mock saying the same thing, and the store
failing safe.

### A15 · [x] (alif/puku-a15-verdict-span, 2026-11-08) · The verdict on the agent's own trace
An OpenTelemetry "semantic loop" span event, so external tools (Phoenix) see our verdicts on the
agent's trace. **Acceptance:** the verdict lands on the agent's own trace, and the collector
forwards it to Phoenix.

**Done.** The contract side merged first (PR #53, `8213cef`), so the brain branch rebased cleanly
onto it.

**The problem it solves.** The agent's *behaviour* lives on an OpenTelemetry trace — in Phoenix,
in Grafana, in whatever the customer already looks at. The brain's *decision* about that behaviour
lived only in CloudSentinel's own tables: an alert row, a verdict row, an action row. So the cause
and the effect were on two different screens, and the person asking *"why did CloudSentinel pause
this agent?"* had to open both and join them by hand.

**It reaches Phoenix without touching anybody else's folder.** Phoenix is fed by the collector,
and the collector forwards the **raw OTLP body** it received — `phoenix.submit(body, ctype)` — not
the rows it normalized out of it. A span *event* only exists in that raw body, so the event
survives the whole way to Phoenix with **one line changed in `telemetry/`** (none) and none in
`shared/store.py` (Fojle's). The brain therefore emits a real OTel span over OTLP/HTTP to the
collector, carrying the agent's own `trace_id` and the judged span as its `parent_span_id`.

**The event, and the numbers.** The verdict is a span event named `semantic_loop`, carrying the
loop score, the repeat count, the confidence, the action and the source. It is an *event* rather
than only attributes because an event reads as *"something happened at this point in the trace"*,
which is what a verdict is. The numbers are there because a verdict without its evidence is an
opinion.

**It cannot break the brain.** Telemetry is the one part of the system allowed to fail: the OTel
packages may be missing, the collector may be down, Phoenix may be slow. The emitter returns a bool
and swallows every exception — a lost verdict is a nuisance, a lost tick is an outage. The
emitter is off unless `CS_VERDICT_OTLP_ENDPOINT` names a collector.

**It cannot judge itself.** The verdict is a span about the agent, so the collector stores it. If
the brain read it back as behaviour, the brain would be judging its own judgement and the loop
score would climb because of the verdicts rather than the agent. The window only counts `chat`
and `execute_tool` spans, so a `cs_verdict` span is ignored — pinned by a test.

**`brain/tests/test_verdict_span.py`** — 24 tests: the verdict on the agent's trace, an
uninstrumented agent still getting one, the trace found from the agent's spans, the event and its
numbers, the reason truncated, the trace id lowercased, a broken sender and a missing sender not
raising, the emitter off without an endpoint, the engine emitting the verdict, the engine surviving
a broken emitter, the collector forwarding the raw body (so the event survives), the collector
storing it as a span, the brain not ingesting its own verdict, and the whole journey — brain →
OTLP → the real collector app → the store — with the trace id and the parent id intact.

---

## Done before this backlog (Wed 4 Nov, lead session)
- Hardening:
  - the judge resists tag-closing agent text, NaN confidence, and cut-off or empty replies
  - malformed spans are skipped
  - commands for unknown agents fail
  - the service validates inputs, and the API returns contract 400s
- Mocks for every contract (`shared/mocks/README.md`).
- A failing tool cycle → PAUSE (loop caught in 3 s).
- The judge cooldown is skipped on new evidence, and the loop detector ignores numbers under 4 digits.
- `/v1/agents/{id}/nodes`, and SDK-enforced control for agents without a container.
- **Not done:** the real Claude run (no key in that cloud session). A1 covers it.

## Notes
(Other people, or the nightly check, write here when something in `brain/` or `shared/` looks wrong.)
- 2026-11-04 (lead): the flaky failure was the CrewAI adapter test (thread-pool event handlers). Fixed in telemetry/ (Fojle's folder) with `flush()` + early-completion handling; nothing to do in brain/. A10 should still watch the `adapters` job.
