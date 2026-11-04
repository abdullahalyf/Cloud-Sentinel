# Repo audit: `main` at 135ded3 (2026-10-26)

About 2,600 lines in total. The core idea works end to end in `--fake` mode. The audit was run on
2026-11-04 with Python 3.13.

## 🚨 Fix immediately

| # | Problem | Where | Fix |
|---|---|---|---|
| S1 | **A real-looking Gemini API key is committed** (`GEMINI_API_KEY=AQ.Ab8RN6…`) in a public repo | `.env.example` (commit c67213c) | **Revoke the key now** at aistudio.google.com → API keys. Replaced with a blank value in this branch. Deleting it from the file does NOT remove it from git history, so revoking is the only real fix |
| S2 | `sentinel/brain.py` imports `google.generativeai`, but `requirements.txt` doesn't list it. A clean `pip install -r requirements.txt` then fails with `ModuleNotFoundError` on `import sentinel.brain`, which breaks the sentinel **and all tests** | `sentinel/brain.py`, `requirements.txt` | The new brain supports Claude (primary) and Gemini (optional) with **lazy imports**, so a missing SDK never crashes the app |
| S3 | `google.generativeai` is **deprecated** ("All support … has ended", FutureWarning at import) | `sentinel/brain.py` | If Gemini is kept, use the `google-genai` package |
| S4 | The brain reads keys with `os.getenv` directly. This breaks rule 3 ("settings only via `shared.config`"), and `config.py` still has an unused `anthropic_api_key` | `sentinel/brain.py`, `shared/config.py` | All keys go through `shared/config.py` |
| S5 | `.env.example` sets `HARD_TOKENS_PER_MIN=500000` and `HARD_CALLS_PER_SEC=50`, but code defaults are 60,000 and 8. With these values hard limits effectively never fire, so the "works even if the LLM is down" backstop is gone | `.env.example` | Restore sane hard limits; tune the demo with soft limits instead |

## ✅ What works (keep)

| Part | Verdict | Notes |
|---|---|---|
| `shared/contracts.py` log protocol + rows | **Keep the idea, extend it** | Clean, stdlib-only, versioned (`cs: 1`). Becomes contracts **v2** (OTel span-based) with the v1 stdout protocol kept as a fallback ingest path |
| `sentinel/collector.py` sliding windows | **Keep → move to `brain/`** | Pure and testable. Exact-hash loop count is good. Paraphrase loops still need similarity detection |
| `sentinel/detector.py` hard/soft rules | **Keep → becomes `brain/rules.py`** | The rules and limits are good. Wrap them in a policy engine plus a breaker state machine |
| `sentinel/engine.py` tick loop | **Keep the shape → `brain/engine.py`** | Background-thread judge, cooldown, and "the guard must never die" are good decisions. Kills move to the infra executor |
| `sentinel/sources.py` DockerSource / FakeSource | **Split** | Event reading becomes telemetry ingest. Docker kill/stats become the `infra/executor` (Taseen). FakeSource becomes `shared/mocks` + `telemetry/simulators` |
| Brain prompt (prompt-injection hardening, JSON verdict, fallback heuristic) | **Keep** | The `<agent_logs>` data-not-instructions framing and the injection red flag are a strong demo point |
| `agents/agent.py` 4 rogue types incl. `paraphrase_loop` | **Keep → `telemetry/simulators/`** | Great demo material. Add `bad_tool_call` and switch emission to the OTel SDK |
| `shared/store.py` Local + Supabase with identical methods | **Keep, extend** | Good pattern. New tables: spans, verdicts, agent_memory, tool_calls, agents |
| `docker-compose.yml`, `docker-compose.scale.yml` | **Keep → `infra/`** | Labels, `restart: "no"`, and the mem_limit + LEAK_CAP safety are right |
| `db/schema.sql`, `db/reset.py`, `db/cleanup.sql` | **Keep → `telemetry/db/`** | Update to schema v2 |
| `scripts/check_setup.py`, `scripts/command.py` | **Keep** | Update to the new CLI and API |
| `dashboard/app.py` | **Baseline only** | It reads the DB directly. In v2 it talks to the C2 REST API (so it can be built against a mock) |
| Tests (14, pass when deps are present) | **Keep, move** | `test_detector`, `test_engine`, and `test_contracts` become the base of `tests/brain` and `tests/shared` |
| Team docs in Bangla (`docs/TEAM.md`, `docs/TASKS.md`) | **Replace** | Superseded by `docs/PLAN.md` + `docs/tasks/<name>.md`. TEAM.md's Git/setup guide stays as the beginner guide |

## ❌ Gaps against the new scope

1. **No OTel.** It uses a custom stdout JSON protocol, so no standard tool can send to us.
2. **No C2 API.** The only commands are KILL and GO_ROGUE via a DB row. There is no pause/resume,
   memory edit, or tool override.
3. **No MCP server.**
4. **No cost in $.** Only tokens, plus a hardcoded `$0.01/1K` in the dashboard. No price table, no ROI.
5. **No eval harness.** Nothing measures detection quality or time-to-detect.
6. **Breaker has no real state machine.** Only `running/warned/killed`, with no half-open/probation
   or pause, and no un-kill.
7. **Loop detection is exact-hash only.** Paraphrase loops rely 100% on the LLM judge, and with
   the fallback (no key) they are never caught.
8. **No CI.** `.github/` is missing, there is no CODEOWNERS, and branch protection is only described in docs.
9. **No K8s.**
10. **Docker kill is in the brain process.** Fine for the demo, but ownership should be the infra layer.
11. The README and docs mention "Claude" while the code uses Gemini. Pick one primary provider
    (decision: Claude primary, Gemini optional; see `DECISION.md`).

## 🗑️ Delete or move

| Path | Action |
|---|---|
| `sentinel/` | Moved to `brain/` (kept as a thin compatibility shim during the migration, removed on Day 2) |
| `agents/` | Moved to `telemetry/simulators/` |
| `db/` | Moved to `telemetry/db/` |
| `docker-compose*.yml`, `agents/Dockerfile` | Moved to `infra/` (a root `docker-compose.yml` stays as the one-command entry point) |
| `docs/TASKS.md` | Replaced by `docs/tasks/*.md` |
| `presentation/` | Moved to `eval/pitch/` (Orin owns `/eval`) |
| The huge GitHub-template `.gitignore` | Keep, but make sure `data/`, `.env`, and `*.db` stay ignored (they are) |
