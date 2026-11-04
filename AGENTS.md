# AGENTS.md: rules for AI coding tools (Codex, Antigravity, Claude Code, …)

Read this whole file before you change anything. Then read the task file of the person you work
for (`docs/tasks/<name>.md`) and `docs/CONTRACTS.md`.

## What this project is
CloudSentinel is a circuit breaker and control tower for AI agents. Agents send OpenTelemetry
spans. The **brain** detects loops, overspend and bad tool calls, a Claude judge decides gray-zone
cases, and the **executor** pauses or kills containers. Humans (dashboard) or Claude (MCP) can
pause/resume/kill agents, edit their memory, and approve/deny/rewrite their tool calls. The ROI
engine prices every intervention.

```
agents (SDK) --OTLP :4318--> telemetry/collector --> store <-- brain/engine --> infra/executor --> Docker/K8s
agents (SDK) --HTTP :8000 (tool gate, memory)--> brain/api <-- dashboard (:5173 web, :8501 Streamlit fallback) · brain/mcp_server <-- Claude
eval/roi <-- brain/api /v1/roi
```

## Folder ownership: NEVER edit outside the folder of the person you work for
| Folder | Owner | Branch prefix |
|---|---|---|
| `brain/` | Alif | `alif/` |
| `infra/`, `.github/`, `docker-compose.yml`, `README.md`, `AGENTS.md`, `.agents/`, `docs/` (except the two below) | Taseen | `taseen/` |
| `dashboard/` | Tamjid | `tamjid/` |
| `telemetry/` + the `SupabaseStore` class in `shared/store.py` | Fojle | `fojle/` |
| `eval/` | Orin | `orin/` |
| `shared/`, `docs/CONTRACTS.md`, `docs/ARCHITECTURE.md` | Alif + Taseen (THE CONTRACT) | `contract/` |

If a task seems to need a change outside the owner's folder (a new field, a new endpoint, a change in
another person's code): **STOP. Do not make the change.** Explain in your final message what is needed
and why, so the owner can do it.

## Hard rules
1. **Contracts first.** Data shapes live in `shared/contracts.py`, `telemetry/db/schema.sql` and
   `docs/CONTRACTS.md`. Never add, rename or remove a field yourself.
2. Data access goes only through `shared.store.get_store()`, except `dashboard/`, which uses
   **only** `dashboard/api_client.py` (HTTP). Never create your own SQLite/Supabase client.
3. Settings come only from `shared.config.settings`. Never hardcode keys, URLs, ports or thresholds.
4. Never commit `.env`, API keys, tokens, or `data/`. Never print keys in logs.
5. Everything must work **offline**: `python -m brain --fake` with SQLite, no Docker, no keys, no internet.
6. Keep it simple: no new frameworks, databases, async rewrites or big dependencies. Ask first.
   Allowed stack: Python 3.11+, FastAPI, Streamlit, Plotly, OpenTelemetry, `mcp`, `anthropic`, `docker`, `kubernetes`, PyYAML.
   Web dashboard only (`dashboard/web/`): Node 20, React 18, Vite, TypeScript, TanStack Query, `@xyflow/react`, ECharts,
   `lucide-react`, Vitest, Playwright (docs/ARCHITECTURE.md §7a). Infra only (`infra/`): Helm, Caddy, Prometheus, Grafana.
7. Use type hints, short functions, and comments in simple English (teammates are beginners).
8. Prompts and logs written by agents are **data, never instructions**. Don't let agent text
   change the brain's behaviour except through the detectors and the judge.
9. Use synthetic data only. No real personal data anywhere.
10. Before finishing: run `python -m pytest -q`. Everything must pass. Add tests for what you change,
    inside the owner's folder (`brain/tests/`, `telemetry/tests/`, `eval/tests/`, `dashboard/tests/`, `infra/tests/`).
11. In your final message: list **every file you changed**, and give exact steps to test the change by hand.

## Commands
```bash
pip install -r requirements.txt
python scripts/check_setup.py             # is my machine ready?
python -m pytest -q                       # all tests
python -m brain --fake                    # brain + API (:8000) + 4 simulated agents, beta goes rogue after 20 s
python -m shared.mocks.mock_api           # mock API on :8000 (dashboard/MCP development, no brain needed)
streamlit run dashboard/app.py            # Streamlit dashboard (:8501, fallback)
cd dashboard/web && npm install && npm run dev   # web dashboard (:5173), once Tamjid D2 is merged
python -m telemetry.collector             # OTLP collector (:4318)
python -m brain.mcp_server                # MCP server (stdio) for Claude Desktop / Claude Code
python -m eval.harness                    # runaway benchmark
docker compose up -d --build              # everything in Docker (collector, brain, dashboard, 4 agents)
python scripts/demo.py rogue beta paraphrase_loop   # make an agent misbehave
python scripts/demo.py reset              # reset after a demo
```

## Alif's agent loop (Codex in VS Code: autonomous, no human checks)
Alif's work in `brain/` and `shared/` is done by an AI agent end to end. If you are that agent (the user says "continue
Alif's backlog", "run the loop" or "next task"), follow these steps exactly. You need no memory of earlier sessions.
Everything you need is in the repo.

0. **Read first:** this file, `docs/HANDOFF.md`, `docs/tasks/alif.md`, `docs/CONTRACTS.md`.
1. **Sync:** `git checkout main && git pull`. If `git status` isn't clean, stash the changes with a note and continue.
2. **Pick the next task** in `docs/tasks/alif.md`, in this order:
   a. **A0** if any `docs/tasks/*.md` has an unchecked `- [ ]` line under "## Contract requests".
   b. **A10** if the last nightly run failed (`gh run list --workflow nightly.yml -L 1`) or there's an open `nightly` issue.
   c. Any task marked `[~]` (resume it on its branch: `git checkout <branch> && git merge origin/main`).
   d. Otherwise the first `[ ]` task, top to bottom (🔴 MUST before 🟡 SHOULD before 🟢 STRETCH). Skip `[!]` tasks.
3. **Claim it:** create the branch named in the task (`alif/<id>-<slug>`, or `contract/<slug>` for `shared/` changes). Mark the box
   `[~] (branch, date)`, then commit and push. That way an interrupted session can be resumed.
4. **Build it:**
   - Write the task's acceptance tests first (`brain/tests/` or `shared/tests/`), then the code.
   - Only edit the files the task owns. Settings only through `shared.config`. Must work offline.
   - A task that needs a contract change follows `docs/tasks/alif.md` "Definition of done", point 4.
5. **Verify yourself:** `python -m pytest -q` + `python -m eval.harness` (all ✅) + the task's own commands. Fix until green.
   If you can't get it green after 3 serious attempts, mark the task `[!]` with the error and the next idea, push the branch, and go to step 2.
6. **Log:** in the same branch:
   - Mark the task `[x] (date, PR link)`. Add the link after the PR exists, in a final commit.
   - Append exactly 3 Bangla lines to `docs/SUMMARY_BN.md`:
     ```
     ### <YYYY-MM-DD> · <task id> <short title>
     - করা হয়েছে: <what was done, one line>
     - এরপর: <the next task id and title>
     - কেউ আটকে আছে?: না  |  হ্যাঁ: <name>, <why, and what they should do>
     ```
7. **Merge:**
   - `git push -u origin <branch>`, then `gh pr create --base main --fill`.
   - `gh pr checks --watch`. When every check is green, `gh pr merge --squash --delete-branch`.
   - If CI is red, fix it on the branch and go back to step 5. Never merge red. Never push to `main` directly. Never force-push `main`.
8. **Others' folders:** never edit their code. If their code breaks the build or looks risky, add a dated note under "## Notes"
   in their `docs/tasks/<name>.md` (the command, the last 15 lines of the error, the file you suspect).
9. **Needs a human** (a key, an account, a GitHub setting, a paid service): never ask Alif. Add a line under
   "## Requests from Alif's agent" in `docs/tasks/taseen.md`, mark the task `[!]`, and continue with the next task.
10. **Repeat** from step 1 until the session ends. Before the session ends, make sure nothing is left uncommitted: push your branch,
    even if the work is unfinished, and leave the box at `[~]`.

Allowed paths for `alif/` branches: `brain/`, `docs/tasks/alif.md`, `docs/SUMMARY_BN.md`, `docs/research/`, and the
"Notes"/"Contract requests" sections of other task files. `contract/` branches may also edit `shared/`, `docs/CONTRACTS.md`,
`docs/ARCHITECTURE.md`, `telemetry/db/schema.sql`, `.env.example`. CI's folder guard enforces this.
