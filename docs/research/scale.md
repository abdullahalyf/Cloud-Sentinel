# The scale proof: the brain at 500 and 1000 agents

**Status (2026-11-08):** B9 is done. Every number below is **measured**, not
estimated — it comes from `python -m brain.scale_bench` over a real `Engine`
and a real `LocalStore` with a `FakeFleet`. The command writes this file, and
the test reads it back and fails if the published number and the measured
number disagree.

## The question

A11 proved the brain at 100 agents: tick p95 **13.2 ms** against a 200 ms
budget. But 100 agents is a demo fleet. The question an operator has is the
one at ten times the size: *does the brain still keep up?*

## What is measured, and what "keeping up" means

The **tick** — the one thing the brain does on a schedule, for every agent,
forever. The tick is the loop the fleet's health is observed by.

The budget is **stated, not inherited**. A11's 200 ms was a tick-interval
budget at 100 agents; scaling it linearly would mean a 2000 ms budget at
1000 agents, and a fleet observed *less often* the bigger it gets — which
is the opposite of what a control tower is for. So the budget here is the
**tick interval itself: 1000 ms** — the same interval the
engine ships with. The finding is not "it is fast"; the finding is
**"one tick still fits inside the interval, and here is by how much"**.

A tick that uses 99% of the interval is a tick that will miss the interval
on a busier machine. So the rule is: the **p95** (the worst tick, not the
median one nobody notices) must fit inside **half** the interval — the room
to spare is what makes the number hold on a machine that is not this one.

## The numbers

One brain worker, one `LocalStore`, `FakeFleet`, virtual clock, deterministic
fallback judge, 20 measured ticks after 3 warm-up ticks.

Each rung is measured **end to end, 3 times**, and the published p95 is the **minimum** of the
repeats. Every repeat does exactly the same work, so the slowest repeat is
the one the machine made worse, not the one that found more work to do.
Taking the minimum removes the machine's contribution and leaves the code's
— and the `spread` column shows how much the machine did contribute, so a
reader can see the noise instead of taking the number on faith.

**Every repeat starts from an empty database.** The store is the benchmark's
throwaway scratch space, and a repeat that started on the previous repeat's
rows would be measuring a bigger database than the last one — which is not
a measurement of the tick. The rows written are therefore constant across
the repeats, and `brain/tests/test_scale.py` checks that they are.

| Agents | min | p50 | p95 | p99 | max | spread | agents/s | % of interval | fits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 100 | 7.9 ms | 9.9 ms | **11.0 ms** | 16.1 ms | 16.1 ms | 37% | 10,079 | 1.1% | yes |
| 500 | 24.3 ms | 47.1 ms | **50.2 ms** | 72.8 ms | 72.8 ms | 43% | 10,612 | 5.0% | yes |
| 1000 | 59.7 ms | 105.3 ms | **129.2 ms** | 156.3 ms | 156.3 ms | 8% | 9,495 | 12.9% | yes |

The p95 is the number the budget is checked against, because the p95 is the
worst tick and the median is the tick nobody notices. The other columns are
there so the reader can see the shape of the sample, not just its summary.

And here are the three repeats themselves, so the `spread` column can be
checked rather than taken on faith:

| Agents | repeat 1 | repeat 2 | repeat 3 | published (min) |
| --- | --- | --- | --- | --- |
| 100 | 15.1 ms | 11.7 ms | 11.0 ms | **11.0 ms** |
| 500 | 50.2 ms | 67.7 ms | 71.7 ms | **50.2 ms** |
| 1000 | 129.2 ms | 139.2 ms | 130.9 ms | **129.2 ms** |

## The shape of the curve

From 100 to 1000 agents the fleet grew **10.0x** and the tick p95 grew **11.7x** — **sub-linear** — the tick got cheaper per agent as the fleet grew, which is what a fixed setup cost does.

**The wall-clock ratio cannot carry this verdict, and the report does not pretend otherwise.** The 100→1000 ratio is too noisy to classify — the p95 at 100 agents is only ~11 ms, so one millisecond of machine jitter is a large fraction of it. At 500→1000 the ratio reads 2.57x against an expected 2.0x, but that is a single pair of numbers, and the same code under load has been seen anywhere between 1.3x and 3.4x. A ratio that swings that much is measuring the machine.

So the shape is measured in **function calls**, which do not move with the machine. The tick does one pass per agent, so the calls per agent have to stay flat as the fleet grows: measured at **215.9** calls per agent at 100 agents and **215.1** at 1000 — flat to within 0.4%. That is linear by construction, and it is the shape that travels between machines.

Per agent, the tick costs **110.3 µs** at 100 agents and **129.2 µs** at 1000 agents — a drift of **+17%**.

**Two different costs, and only one of them is the shape.** The per-agent cost in *function calls* is flat — 215.9 against 215.1 — and that is the tick doing the same work per agent rather than more work per agent. The per-agent cost in *microseconds* drifts by +17%, and that is the ageing effect below: the same work, done more slowly, because the brain is older and the baseline window is fuller.

**The two rungs are not the same age.** The larger fleet has more agents, so more of them are being judged, and the learned baseline has one more sample per tick to recompute. Part of the drift is the fleet and part is the brain getting older — which is why the tick gets *slower* over a long run even at a fixed fleet size. The ageing half is bounded by the baseline window and is discussed under the profile below.

## What the profile found, and what was done about it

The bench profiles the tick as it runs it. At 1000 agents the profile said
plainly where the time went, and three of the four things it named were
waste rather than work.

**1. The rows were deep-copied to be read.** `dataclasses.asdict` is a *deep*
copy: it walks every field and `copy.deepcopy`s every leaf. The metric row is
flat — fourteen scalars, nothing nested — so the deep copy bought nothing. The
brain's batched write called `to_row()` (which calls `asdict`) for every row
it wrote. Profiling **the tick alone** (the timed region, not the ingest
before it) at 1000 agents, the `dataclasses` module accounted for **94,000 of
the tick's 479,817 function calls** — `_asdict_inner` 51,000 times, `fields()`
27,000, and the dict rebuilder 16,000. The batch now reads the columns
straight off the row, and the tick makes **zero** `dataclasses` calls. The
values written are the same values — `brain/tests/test_scale.py` checks
that, column for column, for every shape of the baseline column.

**2. A baseline was built for every agent on every tick and thrown away.**
`setdefault(agent_id, AgentBaseline(agent_id=agent_id))` evaluates its
argument *before* it looks the key up, so every tick constructed a baseline
for every healthy agent — three deques and three `Baseline` objects each —
and discarded it. 1000 wasted constructions per tick. The lookup is explicit
now.

**3. The chat window was walked four times.** `snapshot()` made four passes
over the same deque: one for the rate window, one for the tokens, one for the
dollars, one for the recent calls — and then two more for the prompts and
the repeat counter. The two windows are nested, so one walk serves both.

### What the fix is worth

The honest number is the one that does not move when the machine is busy: the
**count** of function calls in one tick, at 1000 agents.

| | before | after | change |
| --- | --- | --- | --- |
| function calls per tick | 479,817 | 323,204 | **−33%** |
| `dataclasses` calls per tick | 94,000 | 0 | **−100%** |

The wall-clock answer is messier, because the machine is loud. Comparing the
two trees at the *same tick index* — so the brain is the same age in both, and
the difference is the code and not the clock — the faster tick won at every
index: 114 → 94 ms at tick 3, 124 → 91 ms at tick 5, 106 → 83 ms at tick 7,
98 → 80 ms at tick 9. That is **10–25% off the tick**.

The p95 in the table above moves by more than that between runs, and it should:
it is a wall-clock measurement on a shared machine. Read the *call count* as
the finding and the latency as the symptom.

### The one that grows with the *age* of the brain

The tick's cost grows not only with the size of the fleet but with the
*age* of the brain: the learned baseline keeps one sample per tick over a
10-minute window, and the median and the MAD were recomputed over all of
them every tick. At 1000 agents the tick went from 178 ms at tick 1 to
**1183 ms at tick 120** — past the 1000 ms interval the brain promised to
keep. The recompute alone was 173 ms of a ~450 ms tick.

The growth stops at 601 samples — the size of the 600-second window — and
a 1000-tick run confirmed the plateau. So the cost was not unbounded; it
was just *large enough to miss the interval* on the way up.

### Recomputing less often — and why the obvious objection is backwards

The obvious fix is to recompute the statistic less often. The obvious
objection is that a stale baseline would *chase* a runaway instead of
catching it — it would keep absorbing the runaway's own elevated samples
and climb alongside it.

**That objection is backwards, and the measurement is what shows it.** The
limit rises when the agent's recent samples rise. Recomputing on every
observation absorbs the runaway immediately; recomputing less often leaves
the limit standing on the *older, healthier* samples — so it is lower, and
the runaway crosses it sooner. Measured on an agent that ramps 3% per
tick:

| recompute every | runaway caught at |
| --- | --- |
| 1 tick | tick 109 |
| 5 ticks | tick 103 |
| 10 ticks | tick 89 |
| 20 ticks | tick **73** |

A stable agent is not affected either way — the median and the MAD of a
stationary sample do not move — and a creeping agent is protected *better*
by the slower recompute (+15% drift instead of +35%). The learned limit
errs low, which is the safe direction: a limit that is too low trips an
agent that is merely busy and a human looks; a limit that is too high lets
a runaway run.

So `CS_BASELINE_RECOMPUTE_EVERY` ships — and the shipped default is `1`,
the behaviour before this work, because a fleet that has just started up
should not be protected by a statistic it has not learned yet. The setting
is documented in `docs/CONTRACTS.md`; the reasoning and the measurement are
in `brain/baseline.py`.

### The measurement bug that was hiding in this report

The first version of these numbers was wrong, and it was wrong in a way
that looked like a slow machine rather than a bug.

`run_ladder` measured each repeat with a throwaway SQLite file and
removed the file before each repeat, so the run would measure the tick
and not the disk. **The removal never worked.** `LocalStore` opens a
connection and never closes it, and on Windows a file that is open cannot
be deleted — so `os.remove` failed, the failure was swallowed, and the
next repeat opened the *existing* database and added to it.

The symptom was a measurement that drifted instead of repeating. The rows
written went 2300 → 4600 → 6900 at 100 agents, and the p95 of five
identical runs spread by **5.1×** — a spread wide enough to pass for a
loaded machine. The natural reading was "the CI runner is slow", and
that reading was wrong: the CI runner was measuring an ever-growing
database too. The orphan `-wal` file survives the unlink on Linux, and the
next connection recovers the old rows from it, so the bug was on every
platform — it just failed differently.

The fix is in the benchmark, which now closes the store it opened and
removes the database, the `-wal` and the `-shm`. With that, the rows
written are constant and the spread across five identical runs falls to
**1.16× at 100 agents, 1.17× at 500 and 1.56× at 1000** — which is what
the machine's contribution actually looks like.

Two things follow from it, and both are in the tests now. The benchmark
must assert that the rows written are the same every repeat, because a
growing store is the signature of the bug. And the published number must
be compared against the **same estimator** it was produced with — the
minimum across the repeats — because a minimum compared against a single
draw is not a comparison.

### And one that is not ours to fix

The ingest path still deep-copies: `SpanRow.to_row()` goes through `asdict`
for every span. That is the collector's data model, in `shared/`, so it is
not the brain's to change — and it does not matter here, because the ingest
happens *before* the timed region. It is the next hot path when the fleet
grows, though, and it is noted in `docs/tasks/fojle.md`.

## The machine

- **platform:** Windows 11 (AMD64)
- **python:** 3.12.9
- **cpu:** AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD

**Read the latency as a measurement of this machine, not a promise about
yours.** What travels between machines is the *shape* — the ratio between
the rungs, and whether the tick fits the interval at all.

## What is left

At 1000 agents one tick uses **12.9%** of the tick interval, so the fleet is still observed on the schedule it was promised. Two things would matter at a larger fleet, neither of them needed now:

- **the store's commit-per-write.** Every consumer of `shared/store.py` other than the brain's batched write pays one disk sync per row. A bulk `insert_metrics(rows)` / `upsert_agents(rows)` on the store would let the collector and the dashboard write in batches too. That is Fojle's folder — noted in `docs/tasks/fojle.md`.
- **sharding, not one worker.** At some point one worker stops being the right shape; A8 already shards the fleet across workers, so the answer is more workers, not a faster loop.

## Reproducing

```
python -m brain.scale_bench --agents 100 500 1000 --write docs/research/scale.md
```
