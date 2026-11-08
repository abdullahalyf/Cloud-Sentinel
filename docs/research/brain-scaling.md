# Brain scaling: N workers, one fleet

**Status (2026-11-08):** A8 is done. The numbers below are **measured**, not estimated — they come
from `brain/tests/test_sharding.py`, which drives two real `Engine` objects over one `LocalStore`
file with 50 `FakeFleet` agents on a virtual clock. Every acceptance case in `docs/tasks/alif.md` is
a test that fails if the property breaks.

## The problem

One brain process watches the whole fleet. That is fine for four agents and a hackathon, and wrong
for a hundred: one process is one point of failure, one CPU's worth of work, and one SQLite
connection doing everything. The obvious fix — run N brains — is wrong in a worse way. Two brains
watching the same agent pause it twice, judge it twice, and count every metric twice.

So the hard part of horizontal scaling here is not running more processes. It is **making sure that
at every moment, exactly one worker is responsible for each agent**.

## How the ownership is decided

**Rendezvous hashing.** For an agent and a worker, the weight is
`sha1(agent_id + "\x00" + worker_id)`. The owner of an agent is the worker with the **highest**
weight among the workers that are currently alive.

Two details that look like style but are the whole design:

**Never Python's `hash()`.** It is randomised per process (`PYTHONHASHSEED`), so two workers would
compute different owners for the same agent — and each would think it owned everything, because
"the highest hash wins" would be computed over a different set each time. `sha1` is stable across
processes, machines and runs. The test `test_the_owner_is_the_same_in_every_process` pins this to the
exact digest.

**The separator matters.** `("ab", "c")` and `("a", "bc")` hash the same without a `\x00` between
them — two different (agent, worker) pairs would land on the same weight.

**Highest, not lowest and not a modulus.** With rendezvous hashing, when a worker dies only *its*
agents move. With modulo hashing, adding or removing a worker reshuffles nearly the whole fleet,
every agent jumps to a different worker, and the fleet thrashes. The test
`test_only_the_dead_workers_agents_move` checks exactly that: the agents of the workers that stayed
alive do not move.

## The heartbeat

Every worker writes a row into the `workers` table (`worker_id`, `started_at`, `last_seen`,
`agents_owned`, `pid`) every `CS_WORKER_HEARTBEAT_SECONDS` (default 2 s). A worker that has not
beaten for `CS_WORKER_STALE_SECONDS` (default 10 s) is dead, and its agents are up for grabs.

Three rules in the window, and all three matter:

| Rule | Why |
|---|---|
| `stale_seconds` **>** `heartbeat_seconds` | A worker that beats every 2 s must not be declared dead after 1 s of silence. The 10 s window is 5 heartbeats wide. |
| `stale_seconds` **≤** 15 s | The takeover budget. 10 s of staleness + up to one tick of noticing = 12 s observed. |
| A failed heartbeat **does not** kill the worker | If the write fails (the database is locked) and the worker stops beating, the others would take over agents it is *still running*. The heartbeat is swallowed and logged; the worker keeps working. |

**The liveness test is done by the shard, against the shard's own clock** — not inside the store.
The store's `time.time()` is a different clock from the one the heartbeats are stamped with, and a
worker whose clock is off (or a test on a virtual clock) would see every peer as dead and take over
the whole fleet. Two workers acting on one agent is the one bug that must never happen, so the
conservative direction is the safe one: if in doubt, wait for the stale window.

**A worker always counts itself alive**, even if its own last heartbeat failed a moment ago. It is
running; it knows it. If it counted itself dead, the others would take its agents while it was
still working on them.

## The command rule

Both workers read the same pending commands. If both ran them, the agent would be paused twice and
the action counted twice. So a command is only run by the worker that **owns the agent** the
command is for. A command for somebody else's agent is left alone — it is not an error, it is
somebody else's work.

The test `test_no_command_runs_twice` posts one `PAUSE` with two workers running and asserts that
exactly one `PAUSE` action was recorded.

## The numbers

Measured on the acceptance setup: 2 `Engine` objects, one `LocalStore` file, 50 `FakeFleet` agents,
virtual clock, judge in `fallback` mode (no network).

| Measurement | Target | Measured |
|---|---|---|
| Every agent owned by exactly one worker | no overlaps, no gaps | **24 / 26** — disjoint, union = all 50 |
| Both workers get a share | not 49/1, not 50/0 | **24 and 26** |
| Takeover after a worker dies | ≤ 15 s | **12.0 s** |
| No command runs twice | exactly 1 | **1** |
| Tick p95 at 50 agents | < 200 ms | **194 ms** (p50 173 ms, max 212 ms) |

The takeover takes 12 s because it is 10 s of staleness plus up to one tick of noticing. It cannot
be faster without risking two workers on one agent, and 12 s is comfortably inside the 15 s budget.

### The tick is too close to the line

194 ms against a 200 ms target passes, but with no margin — and the tick grows linearly with the
fleet size. A profile of the same run says where the time goes:

```
   ncalls  tottime  cumtime  filename:lineno(function)
    6850  16.387     16.387  {method 'commit' of 'sqlite3.Connection' objects}
    3356   0.060      8.560  store.py:210(insert_metric)
    3356   0.040      8.394  store.py:175(upsert_agent)
    3356   0.060      6.820  state.py:104(snapshot)
```

**`sqlite3.Connection.commit` is 64% of the whole tick** (16.4 s of 25.6 s). `LocalStore` commits
once per write, and the brain writes two rows per agent per tick — `insert_metric` and
`upsert_agent`. Fifty agents is 100 separate transactions, 100 disk syncs.

The fix belongs in `shared/store.py` (Fojle's folder): a `store.transaction()` context manager that
defers the commit, or bulk `insert_metrics(rows)` / `upsert_agents(rows)` methods that commit once
for the batch. The brain would then wrap one tick in one transaction. The note is in
`docs/tasks/fojle.md` — with the numbers and the profile.

Until then, **the tick budget holds at 50 agents and would not hold at 100.** That is A11's job to
measure properly (100 agents, the engine's own perf work).

The next biggest cost is the injection scan (`injection.py:355 score_text`, 4.8 s, 19% of the tick)
— 63 000 regex searches over the agent text. It is worth caching the score per prompt hash.

## Running more than one brain

```bash
python -m brain --worker --worker-id brain-1     # no API, one shard of the fleet
python -m brain --worker --worker-id brain-2
python -m brain                                # the API and the brain itself
```

`--worker` starts the engine with a shard and **no API**: the API belongs to the brain process, and
two APIs on one port would just fight. The workers only watch and act.

The worker id defaults to `hostname-pid`, so two workers on one machine are told apart. The
hostname is in it because two containers on one host can share a pid namespace and then share a pid.

The store must be shared by all of them, so it is SQLite in **WAL** mode (already on) with a 10 s
busy timeout (`sqlite3.connect(..., timeout=10)`) — several processes writing the same file is the
point of the whole exercise.

## What the fake fleet does *not* test

`FakeFleet` generates its own spans, so two workers over one fake fleet would generate the spans
twice. In the acceptance tests the fleet steps once and both engines read the same spans, which is
what the real system does (the collector writes the spans, the brain reads them). A real
multi-process run should use the Docker executor or the collector, not the fake fleet.

## The files

| File | What it is |
|---|---|
| `brain/sharding.py` | The hashing, the shard, the heartbeat, the takeover. |
| `brain/engine.py` | `owns()` and `_reshard()` — the engine only touches what the shard gives it. |
| `brain/__main__.py` | `--worker` and `--worker-id`. |
| `brain/tests/test_sharding.py` | 30 tests: the hashing, the heartbeat, the four acceptance cases, the p95. |
| `shared/store.py` | The `workers` table and the three heartbeat methods (contract folder). |
| `shared/tests/test_sharding_contract.py` | The settings and the table, on the contract side. |
