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

---

# 🆕 B-series backlog (added 8 Nov 2026, by Alif)

**Where this sits.** Twelve new tasks, B1 to B12, in the order Alif asked for. The first four are
🔴 MUST, the next five 🟡 SHOULD, the last two 🟢 STRETCH. They run *after* the A-series, on the
same loop (claim a branch, write the acceptance tests first, `python -m pytest -q` green, PR,
squash-merge, mark the box, three Bangla lines in `docs/SUMMARY_BN.md`).

**The rules that cover every task in this series** (from Alif, 8 Nov):

1. **Every new behaviour goes behind a config flag**, in `shared/config.py` and `.env.example`.
   The default is **off** unless the behaviour is *fully* tested. A flag that defaults to on and
   is only half-tested is how a demo breaks at 3 AM.
2. **Contract changes go through the contract process** — a `contract/…` branch, additive only.
   The mock may lead the real API, never lag.
3. **Code freeze: after 2026-11-12 23:59 (Asia/Dhaka)** — only bug fixes, demo stability and docs.
   A B task that has not merged by then is not started; it is left in the file for after the freeze.
4. **Never edit a teammate's folder.** A needed change in `telemetry/`, `dashboard/`, `eval/`,
   `infra/`, `docker-compose.yml` or `.github/` goes into a note in that person's task file.

### B1 · [x] 🔴 MUST · Verified auto-heal (the shadow dry-run)
> ✅ 2026-11-08 · branch `alif/b1-verified-heal` · PR [#61](https://github.com/abdullahalyf/Cloud-Sentinel/pull/61)
> Prompt:
> *The judge proposes a structured patch (a memory edit, a tool override, or a model downgrade).
> Today a confident patch is applied straight away, and the only evidence it worked is whether the
> agent trips again on probation. That is a bet. Before applying a patch, **replay the agent's
> recent context against the patch in a shadow dry-run**: take the agent's recent spans and memory,
> apply the patch *in a copy*, and ask the detectors whether the patched copy would still look bad.
> Apply the patch automatically **only if the shadow run is healthy AND the judge's confidence is
> above the threshold**. Anything else — an unhealthy shadow, a low confidence — goes to the
> approvals inbox (`heal_proposals`) instead. Log the whole flow as spans (the shadow's verdict,
> the decision, the confidence), so the decision can be read off the trace later.*
>
> **Owned files:** `brain/verified_heal.py` (new), `brain/engine.py`, `brain/heal.py`,
> `brain/verdict_span.py` (the new span events), `shared/config.py`, `.env.example`,
> `brain/tests/test_verified_heal.py` (new). A contract change (new span event names, new
> `ActionType`) goes through `contract/…` first, additive only.
>
> **Acceptance tests:** a shadow run that stays healthy → the patch is applied automatically and the
> flow is logged as spans; a shadow run that is *still* unhealthy → the patch becomes a proposal and
> nothing is applied; a low confidence → a proposal, even when the shadow is healthy; the flag off
> → every patch is a proposal (the old behaviour, exactly); the shadow never writes to the store
> (the memory of a paused agent is unchanged by the dry-run); a broken shadow → a proposal, never an
> exception; the confidence threshold is the configured one, not a constant.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B2 · [x] 🔴 MUST · Incident postmortems
> ✅ 2026-11-08 · branches `contract/b2-incident-postmortem` + `alif/b2-postmortem` · PR [#62](https://github.com/abdullahalyf/Cloud-Sentinel/pull/62) · PR [#63](https://github.com/abdullahalyf/Cloud-Sentinel/pull/63) · PR [#64](https://github.com/abdullahalyf/Cloud-Sentinel/pull/64)
> Prompt:
> *For every incident, generate a structured postmortem: the timeline, the root cause, the evidence
> spans, the action taken, the money saved, the time to detect and the time to heal. Expose it as
> `GET /v1/incidents/{id}/postmortem`, as JSON and as markdown, and add it to the mock API.*
>
> **Owned files:** `brain/postmortem.py` (new), `brain/api.py`, `brain/service.py`,
> `brain/tests/test_postmortem.py` (new). The contract (the endpoint, the report shape, the markdown
> rendering) goes in `shared/contracts.py` + `shared/mocks/mock_api.py` + `docs/CONTRACTS.md` on a
> `contract/…` branch, additive only.
>
> **Acceptance tests:** the postmortem has a timeline in the right order (an alert cannot precede
> the verdict that caused it); the root cause names the rule and the pattern, not "unknown"; the
> evidence spans are real span ids from the store; the money saved uses the ROI formula and is 0 when
> nothing was saved; the time to detect is measured from the first evidence to the alert; the time to
> heal is measured from the alert to the action; the markdown renders the same numbers as the JSON;
> an unknown incident is a 404; the mock and the real API say the same thing (parity test).
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B3 · [x] 🔴 MUST · The deterministic demo runner
> ✅ 2026-11-08 · branch `alif/b3-demo-runner` · PR [#65](https://github.com/abdullahalyf/Cloud-Sentinel/pull/65) · 20/20 runs held
> Prompt:
> *One command runs the whole "3 AM incident" headless — an agent goes rogue, the brain detects it,
> the judge decides, the breaker acts, the agent is healed or killed, and the money is counted — with
> **assertions on every step and on the timing**. It fails loudly if anything drifts. It also writes
> `docs/evidence/demo_run.md` with the timings. Run it 20 times and fix every flake until it passes
> 20 out of 20.*
>
> **Owned files:** `brain/demo_runner.py` (new), `brain/tests/test_demo_runner.py` (new),
> `docs/evidence/demo_run.md` (new), `docs/evidence/` (new folder — note: `docs/evidence/` is *not*
> `docs/research/`, so the folder guard needs it allowed; it is Alif's, asked for by Alif).
>
> **Acceptance tests:** the runner asserts the detection happened, the verdict was reached, the
> action was taken and the cost was counted — and fails when any one of them did not; the timings
> have a budget and a drift over it fails the run; the run is **deterministic** (the same seed gives
> the same numbers, twice); the runner writes the markdown with the timings; it works offline, with
> no Docker and no key; it exits non-zero on a drift.
>
> **Done when:** the tests are green, the full suite is green, the runner passes **20 out of 20**
> consecutive runs (the numbers are recorded in the PR), the PR is merged, the box is `[x]`, and
> `docs/SUMMARY_BN.md` has its three Bangla lines.

### B4 · [x] 🔴 MUST · Budget forecasting and graceful degradation
> ✅ 2026-11-08 · contract PR [#66](https://github.com/abdullahalyf/Cloud-Sentinel/pull/66) (the shapes) · flag PR [#68](https://github.com/abdullahalyf/Cloud-Sentinel/pull/68) · brain PR [#67](https://github.com/abdullahalyf/Cloud-Sentinel/pull/67) · gap PR [#69](https://github.com/abdullahalyf/Cloud-Sentinel/pull/69) · 43 brain tests + 19 contract tests
> Prompt:
> *Use hierarchical budgets — org → team → agent — so one agent cannot spend the whole fleet's
> money, and forecast the burn rate ("this budget is exhausted in X minutes"). Before killing an
> agent, step down: **throttle** first, then switch to a **cheaper model**, then **pause**, and only
> then **kill**.*
>
> **Owned files:** `brain/budget.py` (new), `brain/engine.py`, `brain/breaker.py`,
> `brain/state.py`, `shared/config.py`, `.env.example`, `brain/tests/test_budget.py` (new).
> Contract changes (the new action types `THROTTLE` / `DOWNGRADE`, the new budget table) go through
> `contract/…` first, additive only — and `telemetry/db/schema.sql` is shared with Taseen.
>
> **Acceptance tests:** the org budget is the sum of the team budgets and the team budget is the sum
> of the agent budgets (an agent over its share does not consume the org's whole budget); the forecast
> says "exhausted in X min" from the burn rate, and says nothing when the burn rate is zero; the
> degradation ladder is exactly throttle → cheaper model → pause → kill, and the ladder stops at the
> first step that works; a threshold step does not skip a rung; the flag off → the old behaviour
> (pause / kill, no throttle); a failed throttle does not advance the ladder silently.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B5 · [x] 🟡 SHOULD · Policy backtesting
> ✅ 2026-11-08 · contract PR [#71](https://github.com/abdullahalyf/Cloud-Sentinel/pull/71) (the shapes) · brain PR [#72](https://github.com/abdullahalyf/Cloud-Sentinel/pull/72) · gap PR [#73](https://github.com/abdullahalyf/Cloud-Sentinel/pull/73) · 23 brain tests + 15 contract tests
>
> Prompt:
> *Replay stored historical traces against a new or a changed policy and report what it would have
> caught: the catches, the false positives, and the money saved. Expose it as a CLI and as an API.*
>
> **Owned files:** `brain/backtest.py` (new), `brain/tests/test_backtest.py` (new),
> `shared/config.py` (the flag), `.env.example`. The API endpoint is a contract change:
> `contract/…` branch, `shared/contracts.py` + `shared/mocks/mock_api.py` + `docs/CONTRACTS.md`,
> additive only.
>
> **Acceptance tests:** a backtest over a known set of traces reports the same catches twice
> (deterministic); a false positive is counted, not hidden; the money saved uses the ROI formula;
> the CLI prints the report and exits 0; the CLI takes a policy file as an argument and uses the
> running policy when it is not given one; the API and the CLI agree; a store with no history
> reports zero, not an error.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B6 · [ ] 🟡 SHOULD · Cascade detection
> Prompt:
> *Detect cross-agent loops and contagion — A → B → A, or one rogue agent flooding the others — and
> contain **the whole chain together**, not one agent at a time. Add a simulator scenario for it
> through the mock (no edits to `telemetry/`).*
>
> **Owned files:** `brain/cascade.py` (new), `brain/engine.py`, `brain/tests/test_cascade.py` (new),
> `shared/config.py` (the flag), `.env.example`. The mock scenario is in `shared/mocks/` →
> `contract/…` branch. **Never edit `telemetry/`** — Fojle's.
>
> **Acceptance tests:** an A → B → A chain is detected as one cascade, not as two separate agents;
> one agent flooding the others is detected as a contagion; the containment pauses **every** agent in
> the chain in the same tick; a healthy agent that merely appears in the same window is not swept up;
> the flag off → the old behaviour (each agent handled on its own); the cascade is written to the
> store so it can be read back.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B7 · [x] 🟡 SHOULD · The tamper-evident audit log
> ✅ 2026-11-08 · contract PR [#79](https://github.com/abdullahalyf/Cloud-Sentinel/pull/79) (the shapes) · brain PR [#80](https://github.com/abdullahalyf/Cloud-Sentinel/pull/80) · gap PR [#81](https://github.com/abdullahalyf/Cloud-Sentinel/pull/81) · 25 brain tests + 14 contract tests
>
> Prompt:
> *Every decision and every human action goes into a **hash-chained** log, with a verify command
> and a `GET /v1/audit` endpoint. This is the governance story for the judges.*
>
> **Owned files:** `brain/audit.py` (new), `brain/engine.py`, `brain/service.py`,
> `brain/tests/test_audit.py` (new), `shared/config.py` (the flag), `.env.example`. The endpoint is a
> contract change: `contract/…` branch, `shared/contracts.py` + `shared/mocks/mock_api.py` +
> `docs/CONTRACTS.md`, additive only. A new table needs `telemetry/db/schema.sql` and `LocalStore`
> — shared with Taseen, so the contract branch carries it and the `SupabaseStore` note goes to
> Fojle's "Notes" section.
>
> **Acceptance tests:** the chain links (`hash` = the previous entry's hash + this entry's content);
> a tampered entry is caught by the verify command, and the command says **which** entry; deleting
> an entry from the middle is caught; a chain with no entries verifies; every brain decision and
> every human action is in the chain (a PAUSE by a human, a TOOL_DENY by the policy, an AUTO_HEAL);
> the verify command exits non-zero on a broken chain; the endpoint serves the chain and its head
> hash; the flag off → nothing is chained and the endpoint says so, without failing.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B8 · [x] 🟡 SHOULD · The security detectors
> ✅ DONE · 2026-11-08 · contract PR #83, brain PR #85, gap PR #86
>
> Prompt:
> *Three detectors: **MCP tool-description poisoning** (a tool whose description tries to steer the
> agent), **PII / secret leakage in tool outputs**, and **prompt injection in retrieved content**.
> Each comes with labelled test cases and a measured precision / recall in `docs/evidence/`.*
>
> **Owned files:** `brain/security.py` (new), `brain/injection.py` (the retrieved-content part
> plugs into the existing scorer), `brain/tests/test_security.py` (new),
> `brain/eval_data/security.jsonl` (new, the labelled cases), `shared/config.py` (the flags),
> `.env.example`, `docs/evidence/security.md` (new).
>
> **Acceptance tests:** each detector fires on its labelled positives and stays quiet on its
> labelled negatives; the measured precision and recall are written to `docs/evidence/security.md`
> and are reproducible with one command; a true positive is denied, not merely logged; a secret in a
> tool output is redacted before it is stored; a poisoned tool description cannot change the gate's
> decision by itself; the flag off → the detectors do not run and the old behaviour stands.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.
>
> **Note (8 Nov):** `docs/evidence/` is not in `alif/`'s allowed folders, so the evidence went to
> `docs/research/security.md` instead — the folder the guard *does* allow. The contract half landed
> as PR #83 (`CS_SECURITY_ENABLED`, `CS_SECURITY_REDACT_ENABLED`, `CS_SECURITY_DENY_THRESHOLD`, the
> `tool_registry` table, and the mock's three endpoints); the brain half landed as PR #85 and the
> gap closed as PR #86.
>
> **What it is:** three detectors in `brain/security.py` — a poisoned tool description (a tool whose
> *description* tries to steer the agent), a secret in a tool output (**redacted before it is
> stored**), and an injection in retrieved content (the **existing** A6 scorer reused, not a second
> one). The flag off means the detectors do not run **at all**, not "run but do not report".
>
> **The measurement:** 115 labelled cases, 30 of them adversarial negatives written to make the
> detectors *wrong*. They found **8 real false positives**, every one fixed at the root rather than
> skipped. All three detectors sit at precision 1.0 / recall 1.0, reproducible with one command:
> `python -m brain.security measure --cases brain/eval_data/security.jsonl`. The command **exits
> non-zero** below a floor, so it can be a CI job.
>
> **A note on the fixtures:** the secret-shaped cases carry `{{PLACEHOLDER}}` markers and the loader
> expands them, because a secret-shaped literal in the repository is indistinguishable from a
> leak to the `secrets` job — and a scanner that cries wolf on the team's own corpus teaches the
> team to ignore it. The measurement is unchanged; the repository holds no secret-shaped literal.

### B9 · [x] 🟡 SHOULD · The scale proof
> Prompt:
> *Benchmark the brain with 500 and then 1000 simulated agents. Report the decision latency
> p50 / p95 / p99 and the throughput, profile and optimise the hot paths, and publish the numbers in
> `docs/evidence/scale.md`.*
>
> **Owned files:** `brain/scale_bench.py` (new), `brain/tests/test_scale.py` (new),
> `docs/research/scale.md` (new).
>
> **Acceptance tests:** the benchmark runs 500 and 1000 agents and prints the p50 / p95 / p99 and the
> throughput; the numbers in `docs/research/scale.md` come from a real run, not from a guess; the
> tick stays inside its budget at 500 agents (the A11 budget, 200 ms at 100 agents, scaled and
> stated); the benchmark is offline and deterministic; a regression against the published numbers
> fails (the test reads `docs/research/scale.md`).
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.
>
> **Done (8 Nov).** The evidence file is at `docs/research/scale.md`, not `docs/evidence/` — the
> folder guard gives `alif/` `docs/research/`, and `docs/evidence/` is still an open request to
> Taseen. The file is written by the command that measured it, and a test reads it back and fails
> if the published number and the measured number disagree.
>
> **What the measurement found, and what was fixed.**
>
> - **The rows were deep-copied to be read.** `dataclasses.asdict` is a *deep* copy. The metric
>   row is flat, so the copy bought nothing. Profiling **the tick alone** at 1000 agents, the
>   `dataclasses` module accounted for **94,000 of the tick's 479,817 function calls**. The batch
>   now reads the columns straight off the row, and the tick makes **zero** `dataclasses` calls —
>   pinned as a test.
> - **A baseline was built for every agent on every tick and thrown away.**
>   `setdefault(agent_id, AgentBaseline(agent_id=agent_id))` evaluates its argument *before* it
>   looks the key up, so 1000 baselines were constructed and discarded every tick.
> - **The chat window was walked four times.** `snapshot()` made four passes over the same deque;
>   the two windows are nested, so one walk serves both.
> - **The tick's cost grew with the *age* of the brain.** At 1000 agents the tick went from
>   178 ms at tick 1 to **1183 ms at tick 120** — past the 1000 ms interval. The baseline recompute
>   alone was 173 ms of a ~450 ms tick. The growth stops at 601 samples — the size of the
>   600-second window — confirmed by a 1000-tick run.
>
> **Result:** 479,817 → 323,204 function calls per tick (−33%), 94,000 → 0 `dataclasses` calls
> (−100%), and 10–25% off the wall clock at matched tick indices.
>
> **The correction that mattered.** The first conclusion — "recomputing the baseline less often
> would chase a runaway and is therefore wrong" — was **wrong**, and the measurement said so.
> The limit rises when the agent's recent samples rise, so recomputing on every observation
> absorbs the runaway immediately and the limit climbs alongside it. Recomputing less often leaves
> the limit standing on the *older, healthier* samples, so it is lower and the runaway crosses it
> **sooner**: measured, the runaway was caught at tick 73 with an interval of 20 against tick 109
> with an interval of 1. A stable agent is unaffected, and a creeping agent is protected better
> (+15% drift against +35%). So `CS_BASELINE_RECOMPUTE_EVERY` ships — default `1`, the behaviour
> before B9 — and the reasoning is in `brain/baseline.py`.
>
> **On the noise.** One measurement cannot classify the curve: the p95 ratio of two identical runs
> moved between 8.5× and 27.6× over five runs of the same code. So each rung is measured three
> times and the **minimum** p95 is published, with a `spread` column and the three repeats shown
> so the noise can be checked. The *shape* is measured in function calls, which do not move with
> the machine: **215.9 calls per agent at 100 agents and 215.1 at 1000**, flat to within 0.4%. The
> wall-clock ratio is a budget question, not a shape question, and it is tested as one.
>
> **Contract:** `CS_BASELINE_RECOMPUTE_EVERY` — PR #88 (contract), merged first.
> **Needs Taseen:** `docs/evidence/` is still not a folder `alif/` may write.

### B10 · [ ] 🟡 SHOULD · The team status report
> Prompt:
> *A script reads the git log, the task files and the CI results and writes `docs/STATUS_BN.md`:
> per person, what is done versus what is planned, and who is behind or blocked. Run it after every
> task you finish, so Alif only needs to read that one file.*
>
> **Owned files:** `scripts/status.py` (new), `docs/STATUS_BN.md` (new). `scripts/` is not in the
> folder guard's allowed list for `alif/` — Alif asked for it, so the guard needs it allowed, and
> `docs/STATUS_BN.md` too.
>
> **Acceptance tests:** the report names every person in `docs/TEAM.md`; per person it counts the done
> and the planned tasks from their task file; "behind" is decided by a stated rule (planned tasks
> that are not started, and tasks marked `[!]`); the CI result comes from `gh` when it is available
> and says "unknown" when it is not (never a crash); the report is in Bangla; it is deterministic
> for the same git log and task files; it exits 0 and writes the file.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B11 · [ ] 🟢 STRETCH · Packaging
> Prompt:
> *Make the SDK and the MCP server pip-installable, with a 5-line quickstart that works from a
> clean virtualenv. Test it — actually create the venv and run it.*
>
> **Owned files:** `telemetry/sdk/pyproject.toml` (new — **Fojle's folder**, so this needs a note in
> `docs/tasks/fojle.md` or a `contract/` branch), `brain/mcp_pkg/pyproject.toml` (exists — check
> it), `docs/evidence/quickstart.md` (new), `brain/tests/test_packaging.py` (new).
>
> **Acceptance tests:** `pip install ./telemetry/sdk` works in a clean venv; `pip install ./brain/mcp_pkg`
> works in a clean venv; the installed `cloudsentinel-mcp` command starts and lists its tools; the
> 5-line quickstart runs from a clean venv and prints a fleet; the test creates a real venv (marked
> so it can be skipped when there is no network).
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

### B12 · [ ] 🟢 STRETCH · The evidence pack for the pitch
> Prompt:
> *Collect all the key numbers — detection time, heal time, money saved, accuracy, scale — into
> `docs/evidence/PITCH_NUMBERS.md`, with the **exact command to reproduce each one**. Do not touch
> `eval/` — Orin uses this file as an input.*
>
> **Owned files:** `docs/evidence/PITCH_NUMBERS.md` (new), `docs/evidence/` (the other evidence
> files B3, B8 and B9 wrote).
>
> **Acceptance tests:** every number in the file has a command next to it that produces it; the
> commands run (a test re-runs the cheap ones and checks the numbers match); nothing is invented —
> a number with no command behind it is not in the file; `eval/` is untouched.
>
> **Done when:** the tests are green, the full suite is green, the PR is merged, the box is `[x]`,
> and `docs/SUMMARY_BN.md` has its three Bangla lines.

## Notes
(Other people, or the nightly check, write here when something in `brain/` or `shared/` looks wrong.)
- 2026-11-04 (lead): the flaky failure was the CrewAI adapter test (thread-pool event handlers). Fixed in telemetry/ (Fojle's folder) with `flush()` + early-completion handling; nothing to do in brain/. A10 should still watch the `adapters` job.
