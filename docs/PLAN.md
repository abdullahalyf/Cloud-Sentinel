# PLAN: 8 build days + 3 buffer days

| | Dates (BST) | |
|---|---|---|
| Build | **Day 1 Thu 5 Nov → Day 8 Thu 12 Nov** | features |
| Buffer | **Fri 13 → Sun 15 Nov** | polish, video, submission. **No new features** |
| Hard deadline | **Sun 15 Nov 23:59 BST**. Taseen presses Submit on **Fri 13 Nov** (draft), then re-submits | |

Each person: one folder, one branch prefix, one task file (`docs/tasks/<name>.md`).
Taseen merges to `main`. **Everyone works from the scaffold on Day 1, so nobody waits for anybody.**

## Daily rhythm (all 5)
- **10:00 stand-up (10 min, WhatsApp voice):** yesterday / today / blocked?
- Work on your own branch. Open a **small PR every day** (even if unfinished, mark it Draft).
- **22:00:** Taseen merges green PRs. Everyone runs `git pull origin main` the next morning.
- A PR is mergeable only if CI is green, it touches **only the owner's folder**, and it has no keys.

## Milestones

| Day | Date | Alif (`brain/`) | Taseen (`infra/`) | Tamjid (`dashboard/`) | Fojle (`telemetry/`) | Orin (`eval/`) |
|---|---|---|---|---|---|---|
| 1 | Thu 5 | Review scaffold. Claude judge live with a real key. Semantic loop tuned on the paraphrase sim | Branch protection, CI green, `docker compose up` boots the stubs | Runs mock API + dashboard. Dark theme + agent cards | Setup done, runs `--fake`. Supabase project + `schema.sql` applied | Setup done, runs `--fake`. `docs/QA.md` v1 (10 cases) |
| 2 | Fri 6 | Breaker FSM + policy engine finished, tests | Docker executor: pause/unpause/kill/restart against real containers | Token-flow chart ($/min + tokens/min), state colors | SupabaseStore: 6 write methods | `roi.py` cost functions + tests |
| **CP1** | **Fri 6, 21:00** | **Integration 1:** `python -m brain --fake` + real dashboard (not mock) + Supabase. Paraphrase loop → PAUSE visible on the dashboard | | | | |
| 3 | Sat 7 | C2 API complete (commands, memory, tool gate) | Agent Dockerfile using the SDK, compose for 4 ShopBD agents | Verdict card ("🧠 Claude says…") + actions/alerts feed | SDK: `llm_call`, `task`, export to collector, tested | `roi.py` saved-$ + report, `/v1/roi` shows numbers |
| 4 | Sun 8 | MCP server (all tools) tested in Claude Desktop | `docker compose up` → real agents → real pause/kill end-to-end | **Memory editor** + Resume button | SupabaseStore reads + passes the contract tests. Simulators on the SDK | Harness: scenarios 1–4 |
| **CP2** | **Sun 8, 21:00** | **Integration 2:** Docker mode end-to-end: beta loops → Claude PAUSE → memory edit → resume → probation → healthy. Gamma token bomb → KILL | | | | |
| 5 | Mon 9 | Judge history + suggested fix, injection flag | CI builds images, `make demo` / `make demo-reset` | **Tool-approval cards** (approve/deny/rewrite) | `bad_tool_call` simulator + `real_agent.py` (Claude Haiku) | Harness: scenarios 5–7, benchmark table (markdown) |
| 6 | Tue 10 | Hardening: no crash when executor/judge/DB fail. Perf with 10 agents | K8s (kind) executor + manifests (**cut if CP3 is red**) | **Agent graph** with red cycles + ROI panel | Collector accepts external OTel (LangChain demo snippet) | Pitch deck v1 (10 slides) |
| **CP3** | **Tue 10, 21:00** | **Integration 3: feature freeze for the risky stuff.** Full demo script run once by Orin reading the script. List of bugs → GitHub issues | | | | |
| 7 | Wed 11 | Bug fixes from CP3. `docs/ETHICS.md` safeguards section (with Orin) | Scale demo (10 agents), deploy notes (AWS optional) | Polish: kill flash, big "$ saved", 1080p layout | Bug fixes, `reset.py` v2, cleanup job | QA run: all cases, file issues |
| 8 | Thu 12 | Bug fixes only | Fresh-laptop install test (from README only) | Bug fixes only | Bug fixes only | Demo video script final, rehearse ×3 |
| **CP4** | **Thu 12, 21:00** | **Integration 4: release candidate.** Tag `v1.0-rc`. Demo rehearsed 3× live + 1× offline mode. **Code freeze** | | | | |
| B1 | Fri 13 | Record screen takes | Taseen: fill all 8 submission sections, **Submit draft** | Screenshots for the deck | Prompt library + provenance text | Deck final, video edit v1 |
| B2 | Sat 14 | Fix only show-stoppers | Re-check links (PASS), YouTube unlisted, Judge Access Note not needed (public repo) | — | — | Video final (≤5 min), thumbnail |
| B3 | Sun 15 | — | **Final submit by 18:00 BST** (6 h margin). Tag `v1.0` | — | — | — |

## Integration checkpoint procedure (CP1–CP4)
1. 20:30: everyone pushes. Taseen merges in the order **shared → telemetry → brain → infra → dashboard → eval**.
2. 21:00: Taseen shares a screen and runs the CP script from `infra/README.md` → "Checkpoints".
3. Every failure becomes a GitHub issue assigned to the folder owner, with label `cp1` (etc.).
4. If a CP is red for more than 1 day, apply the **cut list** below.

## Cut list (cut from the top first if behind)
1. K8s executor (keep only the slide + manifest)
2. WebSocket `/v1/stream` (dashboard polls anyway)
3. Gemini provider
4. External LangChain/CrewAI demo
5. Agent graph (keep a simple "loop score" bar instead)
6. `real_agent.py` (keep simulators only; say so honestly in the provenance section)

**Never cut:** the paraphrase-loop → Claude PAUSE → memory edit → resume beat; the hard-limit kill;
tool approval; MCP "pause beta" in Claude Desktop; the $ saved number; offline mode.

## Risk list

| # | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | Beginners blocked by setup (Python, Git, Docker) | High | High | `scripts/check_setup.py`, Day-1 pairing calls, `--fake` mode needs nothing | Taseen |
| R2 | AI tools edit files outside the owner's folder | High | Medium | AGENTS.md + `.agents/rules/`, CODEOWNERS, CI "folder guard" check | Taseen |
| R3 | Contract drift between layers | Medium | High | Frozen `shared/`, contract tests in CI, mocks generated from the same dataclasses | Alif |
| R4 | Claude API key / credit runs out at the demo | Medium | High | Fallback judge, offline mode, cooldown 10 s, Haiku is ~$0.0001/verdict; keep $5 credit reserved | Alif |
| R5 | Venue Wi-Fi fails | Medium | High | Fully offline mode rehearsed; recorded backup video on USB | Orin |
| R6 | Docker Desktop flaky on Windows laptops | Medium | Medium | Demo laptop = Alif's (tested daily), `--fake` fallback | Taseen |
| R7 | NRB collaboration criterion (10%) scores 0 | High | Low-Med | Taseen asks 1 NRB engineer (LinkedIn / mentor list) for a 30-min architecture review by Day 6; document it honestly. Never fake it | Taseen |
| R8 | Submission platform dates differ from ours | Medium | High | Taseen checks the dashboard on Day 1; we plan for the earliest date | Taseen |
| R9 | Leaked secrets (already happened once) | Medium | High | Gemini key revoked; `.env` ignored; CI secret scan (gitleaks); keys only on WhatsApp DM | Taseen |
| R10 | Scope creep ("one more feature") | High | Medium | DECISION.md "not building" list; anything new → issue with label `after-submission` | Taseen |
| R11 | Judge says "fake demo" because agents are simulated | Low | High | One real Claude agent (`real_agent.py`), real containers, real kills, and we say clearly that the rogue agents are deliberate test subjects | Fojle/Alif |
| R12 | Semantic loop detector false-positives on healthy agents | Medium | Medium | Eval benchmark includes a "legitimate burst" scenario; threshold in `.env` | Alif/Orin |
