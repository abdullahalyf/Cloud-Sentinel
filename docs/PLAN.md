# PLAN: 8 build days + 3 buffer days

| | Dates (BST) | |
|---|---|---|
| Build | **Day 1 Thu 5 Nov → Day 8 Thu 12 Nov** | features |
| Buffer | **Fri 13 → Sun 15 Nov** | polish, video, submission. **No new features** |
| Hard deadline | **Sun 15 Nov 23:59 BST**. Taseen presses Submit on **Fri 13 Nov** (draft), then re-submits | |

Each person: one folder, one branch prefix, one task file (`docs/tasks/<name>.md`). Tools: Taseen and Tamjid use Antigravity,
Fojle and Orin use Codex, and Alif runs an autonomous Codex agent in VS Code (`AGENTS.md` → "Alif's agent loop").
New session with no memory? Start with `docs/HANDOFF.md`.
Taseen merges to `main`. **Everyone works from the scaffold on Day 1, so nobody waits for anybody.**

## Daily rhythm (all 5)
- **10:00 stand-up (10 min, WhatsApp voice):** yesterday / today / blocked?
- Work on your own branch. Open a **small PR every day** (even if unfinished, mark it Draft).
- **22:00:** Taseen merges green PRs. Everyone runs `git pull origin main` the next morning.
- A PR is mergeable only if CI is green, it touches **only the owner's folder**, and it has no keys.

## Milestones
Task IDs refer to `docs/tasks/<name>.md`. Each file is ordered 🔴 MUST → 🟡 SHOULD → 🟢 STRETCH.
**Alif** is an autonomous Codex agent working through `docs/tasks/alif.md` (A0–A12) on its own. It merges its own
green PRs and logs to `docs/SUMMARY_BN.md`, so it's not on the day grid. Load: Alif (agent) > Taseen > Tamjid > Fojle > Orin.

| Day | Date | Taseen (`infra/`, lead) | Tamjid (`dashboard/`) | Fojle (`telemetry/`) | Orin (`eval/`) |
|---|---|---|---|---|---|
| 1 | Thu 5 | H1–H5 (keys, ruleset, Alif's laptop, platform), T1 secrets CI, T2 boot | **D1 DESIGN.md**, D2 scaffold | F1 setup + Supabase | O1 setup, O2 QA v1 |
| 2 | Fri 6 | T3 Docker executor, T4 socket proxy | D2 finish, D3 fleet overview | F2 SupabaseStore writes | O3 ROI sentences, O4 RESULTS.md |
| **CP1** | **Fri 6, 21:00** | **Integration 1:** `python -m brain --fake` + the web dashboard (fleet) + Supabase. Paraphrase loop → PAUSE visible. Orin fills CP1 in RESULTS.md | | | |
| 3 | Sat 7 | T5 CI/CD + releases, H6 cloud account | D4 full C2 (commands, memory, tool override) | F3 SupabaseStore reads, F4 collector tests | O6 scenarios ×3 |
| 4 | Sun 8 | T6 CP2 in Docker, T7 K8s on kind | D5 approvals inbox, D6 start | F5 collector hardening (S1–S2) | O7 scenarios ×3 |
| **CP2** | **Sun 8, 21:00** | **Integration 2:** Docker mode end-to-end: beta loops → PAUSE → memory edit → resume → healthy; gamma KILL; delta refund held. K8s executor pauses one Deployment | | | |
| 5 | Mon 9 | T7 finish, T8 Helm, T15 web in compose | D6 LangGraph live graph, D7 burn-down + ROI | F5 (S3–S4), F6 rogues S1–S2 | O8 with vs without |
| 6 | Tue 10 | T9 public deploy (live URL), H7 NRB | D8 incident replay, D9 demo button | F6 S3–S4, F7 OpenAI Agents (S1–S3) | O9 deck outline |
| **CP3** | **Tue 10, 21:00** | **Integration 3: feature freeze for risky work.** The full demo, run by Orin from the demo button on the **public URL**. Bugs → issues | | | |
| 7 | Wed 11 | T11 distributed C2, T12 Prometheus/Grafana, T13 load test 50+ | D10 stage polish, D11 a11y | F7 S4–S5, F8 SDK docs | O10 full QA run |
| 8 | Thu 12 | T14 fresh-laptop test, release `v1.0-rc` | Bug fixes only | F9–F11 (should), bug fixes | O11 video script, rehearse ×3 |
| **CP4** | **Thu 12, 21:00** | **Integration 4: release candidate.** Tag `v1.0-rc` (T5 builds images + release). Demo rehearsed 3× live, 1× offline, 1× on the public URL. **Code freeze** | | | |
| B1 | Fri 13 | H8 fill the 8 sections, **submit the draft** | Deck/README screenshots | Provenance text | Deck final, video edit v1 |
| B2 | Sat 14 | Re-check links, YouTube unlisted | — | — | Video final (≤5 min) |
| B3 | Sun 15 | **Final submit by 18:00 BST**. Tag `v1.0` | — | — | — |

Alif's agent order (`docs/tasks/alif.md`): A0 contract requests (every session) → A1 judge eval → A2 tuning → A3 auto-heal →
A4 adaptive baselines → A5 policy hot reload → A6 injection detection → A7 MCP packaging → A8 sharding → A9 E2E + chaos →
A10 nightly integration (every night) → A11–A12. By CP2: A0–A3. By CP3: A4–A7. By CP4: A8–A9.

## Integration checkpoint procedure (CP1–CP4)
1. 20:30: everyone pushes. Taseen merges in the order **shared → telemetry → brain → infra → dashboard → eval**.
2. 21:00: Taseen shares a screen and runs the CP script from `infra/README.md` → "Checkpoints".
3. Every failure becomes a GitHub issue assigned to the folder owner, with label `cp1` (etc.).
4. If a CP is red for more than 1 day, apply the **cut list** below.

## Cut list (cut from the top first if behind; 🟢 STRETCH items in task files go before any of these)
1. Taseen T11 distributed C2 across nodes (keep the slide + `infra/nodes.yaml` design)
2. Taseen T12 Prometheus/Grafana (the dashboard already shows the same numbers)
3. Fojle F10 CloudWatch export, F9 Supabase realtime/migrations
4. Alif A8 brain sharding (keep the design note + the load-test numbers)
5. Fojle F7 OpenAI Agents adapter (LangGraph + CrewAI already cover P4)
6. Tamjid D8 incident replay (keep the actions feed + burn-down markers)
7. Taseen T8 Helm chart (keep plain `infra/k8s/*.yaml` on kind)
8. Taseen T9 public URL (demo from the laptop, show a recorded run)
9. Tamjid's React dashboard → fall back to the **Streamlit dashboard** (`dashboard/app.py`). Decide at CP2: if D3–D5 aren't on `main`, switch.

**Never cut:**
- the paraphrase-loop → PAUSE → memory edit → resume beat
- the hard-limit kill
- tool approval
- MCP "pause beta" in Claude Desktop
- the $ saved number
- offline mode
- the LangGraph live graph (P1)
- the with-vs-without benchmark table

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
| R13 | Alif's autonomous agent merges a bad change | Medium | Medium | CI must be green; folder guard; nightly E2E; Taseen reads its PRs daily and reverts with `git revert` | Taseen |
| R14 | The React dashboard isn't ready by CP2 | Medium | High | Streamlit stays working as the fallback (cut list #9) | Tamjid |
