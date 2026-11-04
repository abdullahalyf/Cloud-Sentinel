# Judge evaluation: accuracy, latency and cost

**Status (2026-11-04):** the harness, the cases and the offline (fallback) results are real and below.
**The Claude run has NOT happened yet.** `ANTHROPIC_API_KEY` was set in the environment settings, but
this cloud session's container started before that and doesn't see it, and a new session picks it up.
So there are no Claude latency or accuracy numbers here yet. Nothing below is invented.
Alif runs this on Day 1 (one command, about 1 minute, under $0.01):

```bash
python -m brain.judge_bench --judge claude --runs 3 --write    # replaces the block between the bench markers
```

## How it is measured (`brain/judge_bench.py`)
1. It runs the fake fleet on a virtual clock and **captures the exact `JudgeContext`** that the engine
   sends the judge the first time each agent looks suspicious. The judge sees what it would really see in the demo.
2. It adds a hand-made gray-zone case, `legit_burst`: a busy healthy agent with many different orders,
   tools succeeding and a token spike. This is the false-positive test. A PAUSE here is wrong.
3. It calls the judge `--runs` times per case and records the action, confidence, latency, input and
   output tokens, and $ (from `shared/pricing.py`).

## Results
<!-- bench:start -->
Run: 2026-11-04 17:40 UTC · judge `fallback` · model `fallback` · threshold to act `BRAIN_KILL_CONFIDENCE=0.6`

| Case | What it is | Expected | Got (action conf) | Correct | p50 ms | max ms | in tok | out tok | $ / call |
|---|---|---|---|---|---|---|---|---|---|
| paraphrase_loop | same intent, new words, failing tool | PAUSE/KILL | PAUSE 0.70, PAUSE 0.70 | 2/2 | 0 | 0 | 0 | 0 | 0.000000 |
| exact_loop | identical prompt repeated | PAUSE/KILL | PAUSE 0.70, PAUSE 0.70 | 2/2 | 0 | 0 | 0 | 0 | 0.000000 |
| memory_leak | RAM climbing, prompts fine | PAUSE/KILL/WARN | PAUSE 0.70, PAUSE 0.70 | 2/2 | 0 | 0 | 0 | 0 | 0.000000 |
| legit_burst | busy healthy agent (false-positive test) | IGNORE/WARN | WARN 0.55, WARN 0.55 | 2/2 | 0 | 0 | 0 | 0 | 0.000000 |

**Accuracy 8/8** · average cost per judge call **$0.000000** (≈ $0.000 per 1,000 calls)

Last reason per case:

- **paraphrase_loop**: Calls orders_api in a cycle and the last 3 calls all failed: retrying something that keeps failing. Fix: _Set memory "order_4471" to "cancelled - skip it and move on" so the agent stops retrying._
- **exact_loop**: Calls orders_api in a cycle and the last 3 calls all failed: retrying something that keeps failing. Fix: _Set memory "order_4471" to "cancelled - skip it and move on" so the agent stops retrying._
- **memory_leak**: Memory at 70% and climbing: heading for a crash.
- **legit_burst**: Token spend is high but prompts vary.
<!-- bench:end -->

## What the benchmark already taught us (tuning done today)
| Finding | Change | Effect |
|---|---|---|
| A loop's **first** suspicious moment only has `tool_cycle` evidence, because the semantic score needs about 6 prompts to build. The fallback answered WARN, and the PAUSE came one cooldown later | Fallback: a tool cycle whose last 3 calls all failed → PAUSE 0.7 (`infinite_loop`). A succeeding cycle stays WARN | `eval.harness` paraphrase loop **time to detect 13 s → 3 s**. In 10 simulated healthy minutes there were 0 false pauses (the only judge call was delta at 80% budget → WARN) |
| The judge didn't know the breaker's action threshold | The user message now includes `act_when_confidence_at_least` (= `BRAIN_KILL_CONFIDENCE`), and the system prompt explains that a PAUSE below it counts as a WARN | Gives the model calibrated confidences. Check with the Claude run |
| The system prompt didn't name the earliest loop signal | Added: "a tool called in a cycle whose last calls all failed is a loop even while the loop score is still low" | Aligns Claude with the fallback, so the demo behaves the same online and offline |
| Agent text could contain `</agent_logs>` to break out of the data block | `scrub()` neutralises any `<agent_…>` / `</agent_…>` in agent-written text | Covered by `test_agent_text_cannot_close_the_data_tags` |

**Saved $ drops from $6.30 to $2.25** in the harness, because catching the loop 10 s earlier means it
is still cheap when paused. That's the right trade, and the pitch should say "caught in 3 s" rather than quote the bigger $.

## Cost estimate (until the real run replaces it)
Prompt size measured from the real captured contexts: system prompt 1,846 chars, plus a user
message of 1.7–2.5k chars, about **950–1,160 input tokens** at ~4 chars/token. The JSON verdict is about 120 output tokens.
At the `shared/pricing.py` price for `claude-haiku-5-5` ($0.10 / $0.50 per M tokens) that's about
**$0.00016 per judge call, roughly $0.16 per 1,000 calls**. The judge is only called on SUSPICIOUS (with a
`BRAIN_COOLDOWN_SECONDS` cooldown per agent), so a 4-agent demo makes about 5–20 calls. Cost is not a risk;
**latency is**, and only the real run can measure it. Budget: the judge must answer in under 3 s p50 for
the "paused in seconds" story. The hard rules never wait for it.

## What Alif checks in the Claude run
1. `legit_burst` must **not** be PAUSE/KILL in any run. If it is, raise `BRAIN_KILL_CONFIDENCE` to 0.7, or add
   "different item IDs = progress" to the prompt.
2. The loop cases should be PAUSE at ≥ 0.8 with a `suggested_fix` that names `order_4471`.
3. p50 latency under 3 s and max under 10 s. If it's slower, keep `effort: low` and lower `max_tokens` to 400.
4. Zero `fallback` sources. If any appear, the log line `claude judge failed: …` says why
   (bad model ID, no key, timeout).
5. Paste the table (`--write` does it), then commit on `alif/judge-eval`.
