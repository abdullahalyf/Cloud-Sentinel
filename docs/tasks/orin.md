# Orin: Evaluation, ROI and pitch (`eval/`)

**Your goal in one line:** prove, with numbers, that CloudSentinel works and saves money.
Then tell that story in the pitch and the video.

**You own (only edit these):** `eval/` (roi.py, harness.py, tests, `eval/QA.md`, `eval/pitch/`).
**Your branch prefix:** `orin/…`
**Your AI tool:** Codex.

**Contracts you produce:** `build_report()` → `RoiReport` (CONTRACTS §8). The brain's `/v1/roi`
endpoint calls your function.
**Contracts you consume:** rows from `spans`, `actions`, `tool_calls` (§5), and `shared/pricing.py`.

---

## How to work (every task)
1. `git checkout main && git pull` → `git checkout -b orin/<task-name>`
2. Paste the **prompt** into Codex. Read what it changed.
3. `python -m pytest -q`: everything must pass.
4. Do the **"Done when"** check by hand.
5. `git add eval` → `git commit -m "..."` → `git push -u origin orin/<task-name>` → open a PR, reviewer Taseen.

If Codex touches anything outside `eval/`, undo it: `git checkout -- <file>`.

---

## Day 1 (Thu 5 Nov): setup + QA checklist

**Task 1.1: setup.** Follow `docs/TEAM.md`, then run `python -m brain --fake` and, in a second
terminal, `streamlit run dashboard/app.py`.
✅ **Done when:** you watch an agent get paused on the dashboard.

**Task 1.2: QA checklist v1.**
> Prompt for Codex:
> *Read README.md, docs/DECISION.md section 5 and docs/CONTRACTS.md. Rewrite eval/QA.md as a
> markdown table of 20 manual test cases for CloudSentinel with columns: ID, Area, Steps (numbered,
> very simple), Expected, Actual, Pass/Fail. Cover: offline fake mode starts, healthy agent is never
> paused, paraphrase loop gets PAUSED, memory edit + resume returns the agent to healthy, token bomb
> is KILLED by rules, refund over 5000 waits for approval, deny/approve/rewrite a tool call, kill
> switch on a dashboard card, MCP "list agents" in Claude Desktop, no API key (fallback judge), no
> Docker, empty database, killing an already-dead agent, restart a killed agent, $ saved number goes
> up after a kill. Leave Actual and Pass/Fail empty. Only edit eval/QA.md.*

✅ **Done when:** `eval/QA.md` has 20 rows, and you ran at least 5 of them yourself.

---

## Day 2 (Fri 6 Nov): ROI: cost per successful task

`eval/roi.py` already computes total spend and $ saved. You add a new number.

**Task 2.1**
> Prompt for Codex:
> *Read AGENTS.md, docs/CONTRACTS.md section 8 and eval/roi.py. Add a function
> cost_per_successful_task(spans: list[dict]) -> float. A task is a span with operation
> "invoke_agent". It succeeded if task_status == "success". Return total cost_usd of ALL spans
> divided by the number of succeeded tasks, rounded to 4 decimals; return 0.0 if no task
> succeeded. Then make build_report() use it for the key "cost_per_successful_task_usd" and set
> "tasks_succeeded". Add 3 tests in eval/tests/test_roi.py (normal case, zero tasks, a failed task
> is not counted). Only edit files in eval/.*

✅ **Done when:** `python -m pytest eval -q` passes, and `http://localhost:8000/v1/roi` (with
`python -m brain --fake` running) shows `cost_per_successful_task_usd`.

---

## Day 3 (Sat 7 Nov): explain the money

**Task 3.1: readable formula.**
> Prompt for Codex:
> *In eval/roi.py, add a function explain_saving(item: dict) -> str that turns one entry of
> saved_by_action into one English sentence, for example: "Paused beta at $0.042/min; projected 60
> min of waste avoided = $2.52". Use it to add a "sentence" key to every item in saved_by_action
> inside build_report(). Add 2 tests. Only edit eval/.*

✅ **Done when:** the tests pass and `/v1/roi` shows the sentences.

---

## Day 4 (Sun 8 Nov): benchmark harness, scenarios 1–4

`eval/harness.py` runs the real brain against simulated agents on a **fake clock** (fast, so there's
no waiting) and checks whether each failure is caught. One scenario (`paraphrase_loop`) is already done.

**Task 4.1**
> Prompt for Codex:
> *Read AGENTS.md and eval/harness.py. Following exactly the pattern of the existing
> "paraphrase_loop" scenario, add 3 more scenarios to SCENARIOS: "healthy" (no rogue; expected:
> no intervention), "exact_loop" (rogue kind "loop"; expected: intervention), "token_bomb" (rogue
> kind "token_bomb"; expected: intervention). eval/tests/test_harness.py already runs every scenario in
> SCENARIOS and asserts it passed — make sure it still passes. Only edit eval/.*

✅ **Done when:** `python -m eval.harness` prints a table with 4 rows, all ✅.

---

## Day 5 (Mon 9 Nov): scenarios 5–7 + benchmark table

**Task 5.1:** add `memory_leak`, `bad_tool_call` and `injection` scenarios (same prompt as 4.1,
using those kinds).
**Task 5.2:**
> Prompt for Codex:
> *In eval/harness.py, add a --markdown flag that writes the results table to
> eval/BENCHMARK.md with columns: Scenario, Expected, Got, Time to detect (s), $ saved, Result.
> Add a line at the top with the date and the judge mode used. Only edit eval/.*

✅ **Done when:** `python -m eval.harness --markdown` creates `eval/BENCHMARK.md` with 7 rows.

---

## Day 6 (Tue 10 Nov): pitch deck v1
> Prompt for Codex:
> *Read docs/DECISION.md, docs/research/landscape.md (gap table) and docs/research/hackathon.md
> (rubric). Write eval/pitch/deck-outline.md: 10 slides. For each slide give a title, 3 bullet
> points max, and what image or screenshot to show. Order: Problem (a runaway agent bill), Why now,
> Solution, LIVE DEMO, How it works (diagram), Why we win (gap table, 5 rows max), Evaluation
> (benchmark numbers), Business model, Impact & ethics, Team + ask. Simple English.*

Then build the slides in Google Slides from the outline.
✅ **Done when:** the deck link is shared in the team group.

## Day 7 (Wed 11 Nov): run the full QA
Run all 20 QA cases. Fill in "Actual" and "Pass/Fail". For each Fail, open a GitHub issue
(Issues → New issue, include a screenshot) and label it with the folder name (`brain`, `dashboard`, …).
✅ **Done when:** `eval/QA.md` is fully filled in and the issues are created.

## Day 8 (Thu 12 Nov): demo video script
> Prompt for Codex:
> *Read docs/DECISION.md section 5. Write eval/pitch/demo-script.md for a 4–5 minute YouTube video
> as a table: Time, What is on screen, Exact words to say, Who speaks. Follow the judges' order:
> problem → solution → live demo → team → call to action. Short sentences.*

Rehearse the live demo 3 times with a timer.

## Buffer (13–15 Nov)
Record and edit the video (OBS for recording, any free editor), upload it to YouTube as **Unlisted**,
and add a thumbnail. Make sure it's under 5 minutes.
