# Alif: Brain (`brain/`) + contracts co-owner (`shared/`)

**Goal:** the decision core. Detectors, breaker FSM, policy engine, Claude judge, C2 API and MCP
server, all fast, testable, and fail-safe.

**You own:** `brain/`; `shared/` (with Taseen). **Branch prefix:** `alif/…` (`contract/…` for shared).
**Tools:** Claude Code (design, multi-file) + Codex (focused tasks).
**Contracts you produce:** the C2 API (§6), MCP (§7), the metrics/verdicts/actions/agents rows (§5), and policies (§11).
**Contracts you consume:** spans (§4/§5), Executor (§9), `eval.roi.build_report` (§8).

State of the scaffold (Day 0): engine, state windows, semantic-loop + tool-cycle detectors, FSM,
YAML policy, judge (Claude/Gemini/fallback), API and MCP are all implemented with tests, and `--fake` mode runs.
Your job is to **harden, tune and demo-polish** it, and to own integration quality.

---

## Done on Wed 4 Nov (lead session), so start from here
- **Hardening:**
  - The judge can't be broken by agent text that closes our tags, by NaN confidence, or by cut-off or empty replies.
  - Malformed spans are skipped.
  - Commands for unknown agents fail instead of creating ghosts.
  - The service validates actors, sizes and rewrites, and the API returns contract 400s.
  - Tests: `brain/tests/test_hardening.py`, `test_mcp.py`.
- **Mocks:** the mock API now matches the real API's errors and flows (`shared/mocks/README.md`).
- **Tuning:** a failing tool cycle → PAUSE, so loops are caught in 3 s instead of 13 s. Prompt tuned (`docs/research/judge-eval.md`).
- **Not done:** the real Claude run. The key isn't visible in that cloud session.

## Day 1 (Thu 5 Nov): judge live + tune the semantic loop
**First:** put `ANTHROPIC_API_KEY` in `.env` (or open a new cloud session), then run
`python -m brain.judge_bench --judge claude --runs 3 --write` and go through the checklist at the bottom of
`docs/research/judge-eval.md` (no PAUSE on `legit_burst`, p50 < 3 s, zero `fallback` sources). Commit the
table on `alif/judge-eval`.
> Prompt (Claude Code):
> *Read AGENTS.md, docs/ARCHITECTURE.md §5 and brain/loops.py, brain/judge.py. With
> ANTHROPIC_API_KEY set, run `python -m brain --fake -v` and the eval harness `python -m
> eval.harness`. Tune LOOP_SCORE_THRESHOLD and the similarity function so that: paraphrase_loop is
> caught within 15 s, and the "healthy" and "legitimate burst" simulator traffic stays below 0.4.
> Add regression tests in brain/tests/test_loops.py using real strings from
> telemetry/simulators/agent.py. Only edit brain/.*

✅ **Done when:** in fake mode the Claude verdict shows `source=claude` and the PAUSE reason mentions the repeated intent.

## Day 2 (Fri 6 Nov): FSM + policy edge cases
> Prompt (Codex):
> *Read brain/breaker.py and brain/policy.py. Add tests for: a hard limit during probation → killed;
> human RESUME on a non-paused agent is a no-op; on_trip=kill policy; a tool rule with op "contains";
> first-match-wins ordering; a malformed policies.yaml falls back to defaults with a logged error.
> Fix any bug the tests reveal. Only edit brain/.*

✅ **Done when:** `python -m pytest brain -q` is green and FSM coverage is >90% (`pytest --cov=brain.breaker`).

## Day 3 (Sat 7 Nov): C2 API complete + auth
Check every endpoint in CONTRACTS §6 against `shared/mocks/mock_api.py`, since both must return the same
shapes (`shared/tests/test_api_parity.py`). Add the `X-CS-Token` check and a pending tool-call timeout.
✅ **Done when:** the parity test passes, and the dashboard works identically on the mock and the real API.

## Day 4 (Sun 8 Nov): MCP in Claude Desktop
Add to Claude Desktop's config:
```json
{"mcpServers": {"cloudsentinel": {"command": "python", "args": ["-m", "brain.mcp_server"],
  "cwd": "<repo path>", "env": {"CS_API_URL": "http://localhost:8000"}}}}
```
Ask: "Which agent is costing the most? Pause it." Record a GIF of this for the deck.
✅ **Done when:** a pause sent through MCP shows up in the dashboard's actions feed with actor `mcp`.

## Day 5 (Mon 9 Nov): smarter judge
Pass the last 3 verdicts and the agent's memory to the judge, return `suggested_fix`, and flag
injection attempts. Write the judge prompt into `docs/PROMPTS.md` (needed for the prompt library).

## Day 6 (Tue 10 Nov): hardening
Use a chaos list: the executor raises, the DB is locked, the judge times out, 10 agents, 50 spans/s.
The engine must never die, and the tick must stay under 200 ms with 10 agents.

## Day 7 (Wed 11 Nov): ethics + docs
Write `docs/ETHICS.md` (with Orin): human-in-the-loop defaults, the audit trail, data minimisation
(prompt previews ≤200 chars, opt-out), the prompt-injection defence, fail-safe behaviour, and the limits
of the AI judge.

## Day 8 (Thu 12 Nov): bug fixes, release candidate tag with Taseen.
