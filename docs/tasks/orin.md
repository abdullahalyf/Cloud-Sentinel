# Orin: Evaluation, ROI and pitch (`eval/`)

**Your goal in one line:** prove with numbers that CloudSentinel works and saves money, then tell that story in the deck
and the video. You **own the results**: nobody else gets to write the benchmark table.

**You own (only edit these):** `eval/` (roi.py, harness.py, tests, `eval/QA.md`, `eval/RESULTS.md`, `eval/pitch/`).
**Your branch prefix:** `orin/…`. **Your AI tool:** Codex.
**Contracts you produce:** `build_report()` → `RoiReport` (CONTRACTS §8). The brain's `/v1/roi` calls your function.
**Contracts you consume:** rows from `spans`, `actions`, `tool_calls` (§5), `shared/pricing.py`, and the fake fleet
(`shared/mocks/fake_fleet.py`) that the harness drives.

**Every task is short (1–2 hours) and step by step.** Do them in order. If one takes longer than 2 hours, stop and post in the
group what's blocking you.

---

## How to work (every task)
1. `git checkout main && git pull` → `git checkout -b orin/<task-name>`
2. Paste the **prompt** into Codex. Read what it changed.
3. `python -m pytest -q`: everything must pass.
4. Do the **"Done when"** check by hand.
5. `git add eval` → `git commit -m "..."` → `git push -u origin orin/<task-name>` → open a PR, reviewer Taseen.

If Codex touches anything outside `eval/`, undo it with `git checkout -- <file>`.

---

## 🔴 MUST

### O1 (Day 1): setup + watch the demo once
1. Follow `docs/HANDOFF.md` §4 (setup).
2. `python -m brain --fake`, and in a second terminal `streamlit run dashboard/app.py`.
3. Watch beta get paused (about 20 s). Then run `python scripts/demo.py fix beta` and `python scripts/demo.py resume beta`.
✅ **Done when:** you have watched beta go paused → probation → healthy.

### O2 (Day 1): QA checklist v1
> Prompt for Codex:
> *Read README.md, docs/DECISION.md section 5 and docs/CONTRACTS.md. Rewrite eval/QA.md as a markdown table of 20 manual
> test cases with columns: ID, Area, Steps (numbered, very simple), Expected, Actual, Pass/Fail. Cover:
> - offline fake mode starts
> - a healthy agent is never paused
> - the paraphrase loop gets PAUSED
> - memory edit + resume returns the agent to healthy
> - the token bomb is KILLED by rules
> - a refund over 5000 waits for approval
> - deny / approve / rewrite a tool call (a rewrite with no new args shows an error)
> - the kill switch on a dashboard card
> - MCP "list agents" in Claude Desktop (pause/kill ask for confirmation)
> - no API key (fallback judge)
> - no Docker
> - an empty database
> - killing an already-dead agent
> - restarting a killed agent
> - a command for a misspelled agent (alpah) fails and creates no new card
> - the $ saved number goes up after a kill
>
> Leave Actual and Pass/Fail empty. Only edit eval/QA.md.*

✅ **Done when:** `eval/QA.md` has 20 rows, and you've run 5 of them yourself.

### O3 (Day 2): ROI sentences (cost → per-task success is already built)
`eval/roi.py` already attributes cost to tasks (`task_costs`, `tasks_by_agent`, `cost_per_successful_task`). Read it once.
1. Run `python -m brain --fake`, wait 40 s, open http://localhost:8000/v1/roi. Find beta in `tasks_by_agent`.
2. > Prompt for Codex:
   > *Read AGENTS.md, docs/CONTRACTS.md section 8 and eval/roi.py. Add explain_agent(agent_id: str, stats: dict) -> str that
   > turns one tasks_by_agent entry into one sentence, e.g. "beta: 14 tasks, 6 succeeded (43%); $0.0198 spent, $0.0113 wasted;
   > $0.0033 per successful task". If succeeded is 0, say "no successful task yet". Add a "sentence" key to every agent in
   > tasks_by_agent inside build_report(). Add 3 tests in eval/tests/test_roi.py (normal, zero successes, only unattributed
   > spend). Only edit eval/.*

✅ **Done when:** `python -m pytest eval -q` passes, and `/v1/roi` shows a sentence per agent.

### O4 (Day 2): `eval/RESULTS.md`, the results table you fill at every checkpoint
> Prompt for Codex:
> *Only edit eval/. Add a --markdown flag to eval/harness.py that writes eval/BENCHMARK.md with the columns Scenario, Expected, Got,
> Time to detect (s), $ saved, Result, and a first line with the date, the git commit (git rev-parse --short HEAD) and the judge
> mode. Then create eval/RESULTS.md with one table: rows = scenarios, columns = CP1, CP2, CP3, CP4, and each cell holds
> "✅ 3.0 s / $2.25" or "❌". Add a short "How to fill this" section at the top: run `python -m eval.harness --markdown`, then
> copy each row's result into the CP column.*

✅ **Done when:** `python -m eval.harness --markdown` writes BENCHMARK.md, and RESULTS.md has today's numbers in a "Day 2" column.

### O5 (every checkpoint: Fri 6, Sun 8, Tue 10, Thu 12, 20:30): run the benchmark + fill RESULTS.md (30 minutes)
1. `git checkout main && git pull`
2. `python -m eval.harness --markdown`
3. Copy the results into the CP column of `eval/RESULTS.md`. Any ❌ becomes a GitHub issue labelled with the folder name.
4. Commit on `orin/cpN-results` and open a PR.
✅ **Done when:** the CP column is filled, before 21:00.

### O6 (Day 3): scenarios: healthy, exact loop, token bomb
> Prompt for Codex:
> *Read AGENTS.md and eval/harness.py. Following the pattern of the "paraphrase_loop" scenario, add "healthy" (no rogue; expected:
> no intervention), "exact_loop" (rogue kind "loop"; expected: intervention) and "token_bomb" (rogue kind "token_bomb";
> expected: intervention) to SCENARIOS. eval/tests/test_harness.py runs every scenario, so make sure it still passes. Only
> edit eval/.*

✅ **Done when:** `python -m eval.harness` prints 4 rows, all ✅.

### O7 (Day 4): scenarios: legit burst, memory leak, bad tool call
Same prompt as O6, with: `legit_burst` (a busy but healthy agent, expected: **no** intervention; this is our false-positive check),
`memory_leak` and `bad_tool_call`.
✅ **Done when:** 7 rows, all ✅. If `legit_burst` gets paused, open an issue for `brain` with the output (Alif's agent fixes it).

### O8 (Day 5): with vs without CloudSentinel
> Prompt for Codex:
> *Only edit eval/. In eval/harness.py, add run_without(scenario): the same simulated agents and the same virtual duration, but the
> engine never ticks (no detection, no actions), so nothing stops the rogue agent. Measure the total spend and the subject's
> wasted_usd (from eval.roi.tasks_by_agent(store.spans_after(0, limit=100_000))). Add a --compare flag that prints and writes to
> eval/BENCHMARK.md a second table: Scenario, Spend with CloudSentinel, Spend without, Saved, Saved %, Subject success rate
> with / without. Add a test that "without" spends more than "with" for paraphrase_loop.*

✅ **Done when:** `python -m eval.harness --compare` shows, for every rogue scenario, that "with" spends less. Put one sentence in RESULTS.md:
"In the paraphrase loop, CloudSentinel cut spend by X% and was N s to detect."

### O9 (Day 6): pitch deck outline
> Prompt for Codex:
> *Read docs/DECISION.md (sections 2, 2b, 5), docs/research/landscape.md (gap table), docs/research/hackathon.md (rubric) and
> eval/RESULTS.md. Write eval/pitch/deck-outline.md: 10 slides. For each slide: a title, max 3 bullets, and which screenshot or
> number to show (take numbers ONLY from eval/RESULTS.md or BENCHMARK.md, never invent them). Order: Problem (a runaway
> agent bill), Why now, Solution, LIVE DEMO, How it works (diagram), the 5 AgentOps prompts → our features (DECISION §2b),
> Evaluation (with vs without), Business model, Impact & ethics, Team + ask. Simple English.*

Then build the slides in Google Slides from the outline.
✅ **Done when:** the deck link is shared in the group, and every number on it has a source line in the speaker notes.

### O10 (Day 7): full QA run
Run all 20 QA cases on the real system (Tamjid's web dashboard + `python -m brain --fake`). Fill in Actual and Pass/Fail.
Every Fail becomes an issue (with a screenshot), labelled with the folder name.
✅ **Done when:** `eval/QA.md` is fully filled and the issues are created.

### O11 (Day 8): demo video script
> Prompt for Codex:
> *Read docs/DECISION.md section 5 and eval/pitch/deck-outline.md. Write eval/pitch/demo-script.md for a 4–5 minute video as a
> table: Time, What is on screen, Exact words to say, Who speaks. Order: problem → solution → live demo (use the dashboard's
> "Run the 3 AM incident" button) → results (with vs without) → team → call to action. Short sentences.*

Rehearse the live demo 3 times with a timer.
✅ **Done when:** one rehearsal fits in 5:00, and the script is merged.

## 🟡 SHOULD
- **O12 (Day 6–7): scenarios for Fojle's new rogues** (`prompt_injection`, `tool_storm`, `memory_poisoning`,
  `slow_budget_leak`). One scenario per task, the same prompt as O6. The harness drives `shared/mocks/fake_fleet.py`, so first
  check that FakeFleet knows the kind (`grep <kind> shared/mocks/fake_fleet.py`). If it doesn't, add a **Contract request** below,
  and Alif's agent adds it.
- **O13: `explain_saving(item)`**: one sentence per `saved_by_action` entry ("Paused beta at $0.042/min; projected 60 min of waste
  avoided = $2.52"), added as a "sentence" key. 2 tests.
- **O14: 20+ scenarios.** Variations of the existing ones: 2 agents rogue at once, a rogue during probation, a loop that starts after
  60 s, a very slow leak. One per short task, and the expectation must be written down before you run it.
- **O15: QA run at every checkpoint.** Run the 8 "never cut" cases (PLAN.md) at every CP, and add a CP column to `eval/QA.md`.

## 🟢 STRETCH
- **O16: judge comparison slide.** Alif's agent writes `docs/research/judge-eval.md` (accuracy, latency and cost per judge model). Make one
  slide from it, and cite the Hugging Face Open LLM Leaderboard only as outside context (clearly labelled as not our measurement).
- **O17: `docs/ETHICS.md` draft** (ask Taseen first: `docs/` is Taseen's folder): human-in-the-loop defaults, the audit trail,
  data minimisation (prompt previews ≤200 characters), the prompt-injection defence, fail-safe behaviour, and the limits of the AI judge.

## Buffer (13–15 Nov)
Record the video (OBS), edit it, upload it to YouTube as **Unlisted** (under 5 minutes) with a thumbnail. Put Tamjid's screenshots in README.md (ask Taseen to merge).

---

## Notes from the lead review (Wed 4 Nov)
1. **Benchmark numbers:** the brain catches the paraphrase loop at its first failing tool cycle: **3 s to detect, $2.25 saved**.
   "Saved" is low because we stop it early. Say "caught in 3 s", and use O8's with-vs-without numbers for the money story.
2. The judge-only benchmark is `python -m brain.judge_bench` → `docs/research/judge-eval.md` (owned by Alif's agent).
3. `value_usd` that is negative or NaN is stored as 0, so ROI can't be inflated.
4. The harness runs on a **virtual clock**: use `store.spans_after(0, limit=100_000)`, not `recent_spans`.

## Contract requests
(Alif's agent reads this list (task A0). Write: what, why, which task.)
