# The brain at 100 agents: where the time went, and what was done about it

**Status (2026-11-08):** A11 is done. Every number below is **measured**, not estimated — they
come from `brain/tests/test_perf.py` and from profiling a real `Engine` over a real `LocalStore`
with 100 `FakeFleet` agents. The acceptance case (tick p95 < 200 ms at 100 agents) is a test that
fails if the property breaks.

## The starting point

The tick had a 1-second budget and 100 agents to watch. The profile said the tick took **513 ms**,
and that 84% of it was not thinking at all:

```
ncalls  tottime  filename:lineno(function)
  1005    3.464  {method 'commit' of 'sqlite3.Connection' objects}
   500    0.427  brain/state.py:104(snapshot)
  4608    0.338  brain/injection.py:355(score_text)
```

Two things stood out, and neither of them was the brain doing its job.

## The first thing: 200 disk syncs per tick

The tick writes two rows per agent — a metric and an agent row — and the store commits after each
one. At 100 agents that is 200 commits per tick, and 1005 commits in five ticks is exactly what the
profile counted.

The cost was not the write. It was the *commit*: SQLite flushes to disk on every commit, so the
brain was asking the disk to say "yes" two hundred times for one tick's worth of work. The
measurements agreed — the p95 under a write lock was 3914 ms (A9), and the tick's own time was
dominated by a syscall that has nothing to do with detecting a runaway agent.

### The fix: one transaction per tick

`brain/write_batch.py` collects the tick's metric and agent rows and writes them in a single
transaction, on the store's own connection, under the store's own lock.

**Why it is in the brain and not in the store.** `shared/store.py` is Fojle's folder, and the brain
does not edit other people's folders. But the *brain* is the thing that knows it is about to write
200 rows that all belong to the same tick — the store cannot know that. So the brain batches, and
the store keeps its own API.

**Commits per tick: 200 → 1.** The profile after the change:

```
ncalls  tottime  filename:lineno(function)
    10    0.022  {method 'commit' of 'sqlite3.Connection' objects}
```

## The second thing: the same work, redone, every tick

With the disk no longer the bottleneck, the next biggest thing was the regex work: 32,256 calls to
`re.Pattern.search` per five ticks. Two things were re-doing work whose answer was already known:

**The loop score.** `semantic_loop_score` re-tokenizes and re-clusters all 16 recent prompts on
every tick, for every agent. But the window slides by *one* prompt at a time: 15 of the 16 word
sets are exactly the same as they were last tick. `loops.IncrementalLoopScore` keeps the clusters
between calls, caches each prompt's word set, and places only the new prompt — comparing it against
the clusters that are still standing.

**The injection score.** `score_text` was called on the same 12 prompts *twice* per tick (once for
the count, once for the maximum), and the score of a text never changes. `AgentWindow` now caches
it by the text.

After both: `re.Pattern.search` went from **32,256 calls to 945**.

### The one thing the fast path must not get wrong

The loop score is what the detectors act on, so it has to be the *same number* the plain scorer
gives — a faster number that is a different number would be worse than the slow number.

The greedy clustering is order-dependent (a prompt joins the *first* cluster it matches), so the
fast path only runs when the new window is a suffix-extension of the old one: the common case, where
the window slides forward or grows. Anything else — a prompt edited, reordered, or the window
jumping backwards — falls back to recomputing from scratch. `brain/tests/test_perf.py` checks that
the two agree prompt for prompt, as the window slides, as it shrinks, and after a mid-window change.

## The numbers

Tick duration, one brain worker, one `LocalStore`, `FakeFleet`, virtual clock, 20 ticks after
3 warm-up ticks:

| Agents | min | median | p95 | max |
| --- | --- | --- | --- | --- |
| 10 | 3.0 ms | 3.9 ms | 4.1 ms | 5.1 ms |
| 25 | 4.0 ms | 5.0 ms | 6.9 ms | 7.9 ms |
| 50 | 6.0 ms | 7.1 ms | 8.2 ms | 9.1 ms |
| **100** | **8.1 ms** | **11.5 ms** | **13.2 ms** | **14.0 ms** |
| 200 | 14.3 ms | 20.0 ms | 25.1 ms | 46.1 ms |

**At 100 agents: 513 ms → 13.2 ms p95.** The budget is 200 ms, so the tick now uses 6.6% of it.
The curve is close to linear with a small constant, which is what you want from a loop that does
the same amount of work per agent.

For comparison, the A8 measurement (two workers, 50 agents each, shared store) put the tick p95 at
194 ms — over the budget, because each worker was paying 100 commits per tick for its own half of
the fleet. The same fix applies to it: the A8 numbers in `docs/research/brain-scaling.md` were
measured before this change and should be read as the *before* picture.

## The rules the change had to keep

Three things a faster tick must not break, each one a test:

1. **The same rows.** The batch writes exactly what the store's own one-at-a-time writes write.
2. **The learned baseline survives.** The store's rule is that an empty baseline means "no new
   baseline", so the one already stored must not be wiped — and in a batch, where one agent may
   have a baseline and another may not, the two cases have to be handled in the same statement.
3. **A failed batch loses nothing.** If the batched write fails for any reason, the rows are
   written one at a time exactly as before. A batch must never be a way to lose a metric.

## What is left

The tick is now well inside its budget at 100 agents, so the scaling story is settled for the
hackathon's scale. Two things would matter at a larger fleet, neither of them needed now:

- **The store's own commit-per-write.** Every other consumer of `shared/store.py` still pays one
  disk sync per row. A bulk `insert_metrics(rows)` / `upsert_agents(rows)` on the store, or a
  `CS_STORE_BUSY_TIMEOUT_MS` knob, would let the collector and the dashboard write in batches too.
  That is Fojle's folder — it is noted in `docs/tasks/fojle.md`.
- **The 200-agent point.** 25 ms p95, still comfortable, but the max (46 ms) shows the tail
  growing faster than the median. At a fleet of a thousand, the window itself would need to be
  shorter, or the agents sharded across more workers — which A8 already does.
