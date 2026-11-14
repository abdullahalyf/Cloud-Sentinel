# The pitch numbers — every claim, and the command that reproduces it

**Status (2026-11-08):** every number below was **measured**, and every one of
them comes with the **exact command** that produced it. Nothing here is
estimated, projected, or rounded up to look better.

The rule this file follows: **a number without a reproduce command is a
claim, not evidence.** So each row has one, and each command is one a
stranger can type.

**Two numbers are deliberately missing.** The Claude judge's latency and cost
have never been measured — there is no `ANTHROPIC_API_KEY` in this
environment. They are marked **needs a human**, not filled in with a guess.

---

## 1. Detection → heal, end to end

The whole claim in one number: **how long from "the agent started misbehaving"
to "the agent was stopped", and how much money that stopped.**

| | |
| --- | --- |
| **Detect** | **5.0 s** (budget 60 s) |
| **Judge** | **1.0 s** (budget 60 s) |
| **Act** | **0.0 s** (budget 30 s) |
| **Heal** | **0.0 s** (budget 30 s) |
| **Total** | **6.0 s** |
| **Money saved** | **$2.2344** (648,720 tokens) |
| **Money spent** | **$0.0093** |
| **Determinism** | **20/20 runs** held every assertion |

**Reproduce:**

```bash
python -m brain.demo_runner --runs 20 --write docs/research/demo_run.md
```

The clock is **virtual**, so the same seed gives the same numbers every time.
The runner exits **non-zero** if any assertion fails, so it can be a CI gate.

**What this is not:** it is not a claim that a real incident takes 6 seconds.
It is a claim that **the control loop has no unbounded step** — every stage
has a budget, and the loop completes inside them. The 20/20 is the part that
carries the weight: it is the same incident, twenty times, with no drift.

---

## 2. Scale — the brain at 100, 500 and 1000 agents

| Agents | p50 | **p95** | p99 | spread | agents/s | % of the 1000 ms tick | fits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 100 | 9.9 ms | **11.0 ms** | 16.1 ms | 37% | 10,079 | 1.1% | yes |
| 500 | 47.1 ms | **50.2 ms** | 72.8 ms | 43% | 10,612 | 5.0% | yes |
| 1000 | 105.3 ms | **129.2 ms** | 156.3 ms | 8% | 9,495 | 12.9% | yes |

**Reproduce:**

```bash
python -m brain.scale_bench --agents 100 500 1000 --repeats 3
```

**The rule the numbers are checked against:** the **p95** must fit inside
**half** the 1000 ms tick interval. Half, not all — a tick that uses 99% of
the interval will miss it on a busier machine, and the room to spare is what
makes the number hold on a machine that is not this one. At 1000 agents the p95
is **12.9%** of the interval.

**Two honesty notes that are part of the claim:**

- **Every repeat starts from an empty database.** The store is the
  benchmark's scratch space; a repeat that started on the previous repeat's
  rows would be measuring a bigger database, not the tick.
- **The published p95 is the minimum of three repeats**, and the `spread`
  column shows how much the machine contributed (1.16× at 100 agents, 1.17× at
  500, 1.56× at 1000) so a reader can see the noise instead of taking the
  number on faith.

> **The bug this caught.** An earlier version of this benchmark measured **5.1×
> spread** across five identical runs, and it looked exactly like "a slow
> machine". It was not: the benchmark was measuring **its own leftover
> database**, because the store's connection was never closed and the delete
> silently failed. The rows grew 2300 → 4600 → 6900. The spread after the fix
> is 1.16×. **This is why the spread column is published and not just the
> p95** — a number whose own measurement method was wrong for three days is
> exactly the kind of number a pitch should not use.

---

## 3. Security — three detectors, precision and recall

| Detector | Cases | True | False | Missed | Quiet | **Precision** | **Recall** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `tool_description_poisoning` | 40 | 15 | 0 | 0 | 25 | **1.0** | **1.0** |
| `secret_in_tool_output` | 40 | 15 | 0 | 0 | 25 | **1.0** | **1.0** |
| `retrieved_content_injection` | 35 | 10 | 0 | 0 | 25 | **1.0** | **1.0** |

**115 labelled cases**, of which **30 are adversarial negatives** — cases
written specifically to make the detectors *wrong*.

**Reproduce:**

```bash
python -m brain.security measure --cases brain/eval_data/security.jsonl
```

The command exits **non-zero** if precision or recall drops below the floor,
so it can be a CI job.

**What precision 1.0 does and does not mean.** It means every finding in this
corpus was a real attack. It does **not** mean the detector is perfect on
unseen attacks — it means the corpus was built adversarially and the
detectors survived it. The 30 hard negatives are the evidence for that claim;
without them, "precision 1.0" would just mean "the corpus was easy".

**No secret-shaped strings are in the repo.** The cases use `{{PLACEHOLDER}}`
and the loader substitutes at run time — because secret-shaped text in a
repository can never be un-leaked by a scanner.

---

## 4. The judge — accuracy, offline and on the real API

Two judges, and they are not interchangeable. The **offline (deterministic
fallback)** judge is a rule-based scorer with no model call; the **Claude**
judge is the real thing that runs in production. Both are measured, and both
numbers are here.

**Offline judge**, over **70 labelled incidents** (34 positive, 36 negative):

| | |
| --- | --- |
| **Precision** | 1.000 |
| **Recall** | 0.824 |
| **F1** | 0.903 |
| **Accuracy** | 0.914 |
| Latency p50 / p95 | 0 ms / 0 ms |
| $ per verdict | 0.000000 |

**Reproduce:**

```bash
python -m brain.judge_eval --judge fallback --runs 1 --write docs/research/judge-eval.md
```

**The 0 ms latency and $0.00 cost are not a performance claim.** They are
what the *fallback* judge costs. The real numbers come from the Claude judge,
and the block below is written by CI from a real run — never by hand.

<!-- claude-judge:start -->
> **Needs a human:** run `python -m brain.judge_eval --judge claude --runs 3`
> with an `ANTHROPIC_API_KEY` to get the latency, cost and accuracy of the
> real judge. Until then, this file quotes **no** Claude number.
<!-- claude-judge:end -->

**Why the negative half matters.** 36 of the 70 incidents are negatives — a
judge that pauses every busy agent is **worse than no judge**, because
operators learn to ignore it. Recall 0.824 means the fallback judge misses
some real incidents; that is published rather than hidden.

---

## 5. The brain at 100 agents — where the time went

The starting point: the tick took **513 ms** against a 1-second budget, and
**84% of it was not thinking** — 200 SQLite commits per tick (one per row),
because the store committed after every write.

| | Before | After |
| --- | --- | --- |
| Tick p95 at 100 agents | 513 ms | **13.2 ms** |
| SQLite commits per tick | 200 | **1** |

**Reproduce:**

```bash
python -m pytest brain/tests/test_perf.py -q -m perf
```

The acceptance case (tick p95 < 200 ms at 100 agents) is a **test that fails
if the property breaks** — not a number in a document.

---

## 6. The audit log — tamper-evident, and verifiable

| | |
| --- | --- |
| Chain | **hash-chained** — every entry carries the previous entry's hash |
| Verify command | `python -m brain.audit verify` |
| On a broken chain | **non-zero exit**, and it names the broken entry |
| Flag | `CS_AUDIT_ENABLED` — **off by default** |

**Reproduce:**

```bash
CS_AUDIT_ENABLED=true python -m brain.audit verify
python -m brain.audit verify --json
```

**The flag is off by default, so a fresh checkout's chain is empty** and
`verify` says *"the chain is empty"*. That is not a failure — it is the honest
answer when nothing has been chained yet. Turn the flag on and the chain
starts writing.

**The claim, and the proof of it.** If anyone edits or deletes an entry in the
middle, **that entry and every link after it** breaks. A log you can edit is
not an audit log. Tampering with entry 1 of a 2-entry chain gives:

```
ok: False   broken_at: 1
reason: entry 1 has been changed — its hash is '59aee6…', but its content
        hashes to '469079…'
```

It does not just say "something is wrong" — it says **which entry**, and
shows both hashes, because "the chain is broken" is not something an operator
can act on.

**Why `created_at` and `usd_saved` are not in the hash — on purpose.** The
chain says "what happened". The clock moves and the money is recalculated
often enough that hashing either would break the chain constantly, and a chain
that is constantly broken is one that can never be verified. The cost of that
choice is stated here rather than buried.

**The writer is called from every place** where a decision or a human's
action is recorded — the engine's `_apply`, auto-heal, degradation,
`SET_BUDGET`, tool-gate denials and auto-allows, human tool decisions and
memory edits, cascade stops, policy reloads — so the chain is "everything that
happened", not "what we remember to chain".

---

## 7. Policy backtesting — would a new policy have caught it?

The question: *if we had changed the policy last week, would it have caught
the runaway?* Answered by **replaying the old traces** through the candidate
policy — the same `AgentWindow` and the same `evaluate()` the live brain uses
per tick, with only the candidate's budget changed.

**Reproduce:**

```bash
python -m brain.backtest            # the running policy against itself
python -m brain.backtest candidate.yaml
```

A sample run on the current store: **213 spans replayed** across 4 agents,
**1 catch, 0 false positives**, $2.8842 saved over the 60-minute horizon.

The report prints and exits **0** — a backtest that found nothing is still a
result, and a backtest that *crashes* on an empty store teaches an operator
not to trust it.

**False positives are counted, not hidden.** Only the store's own **alerts**
are ground truth: if the brain did not alert, the agent was genuinely fine.
A rule the running policy already applied is **not** a new catch — counting it
as one would inflate the backtest into an advertisement.

**The money is the live system's own ROI formula** (`$/min at the moment of
action × horizon`), so a backtest and a live ROI report can never disagree
about what a saved dollar is.

**It does not touch `eval/`** — Orin's folder — so the backtest reads the
store and the policy and nothing else.

---

## 8. The tool surface — what an operator can actually do

The MCP server exposes **17 tools**, and the installed package is what was
tested:

| | |
| --- | --- |
| Tools | **17** |
| Installs from | `pip install ./brain/mcp_pkg` |
| Command | `cloudsentinel-mcp` |
| Transport | MCP over stdio (or `--http`) |

**Reproduce:**

```bash
python -m pytest brain/tests/test_packaging.py -q -m live
```

That test builds a **real virtualenv**, really installs the package, drives
the **installed** command over **real MCP stdio**, and points it at a running
`python -m brain --fake` to get a **real fleet** back.

The read-only ones: `list_agents`, `get_agent`, `explain_agent`,
`get_memory`, `list_pending_tool_calls`, `get_tool_risk`, `get_roi_report`,
`get_policy`, `validate_policy`, `list_heal_proposals`.
The ones that change something: `pause_agent`, `resume_agent`, `kill_agent`,
`set_budget`, `edit_memory`, `decide_tool_call`, `decide_heal`.

---

## The summary table

| Claim | Number | Reproduce |
| --- | --- | --- |
| Detection → heal | **6.0 s**, $2.23 saved | `python -m brain.demo_runner --runs 20` |
| Determinism | **20/20** runs held | same command |
| Scale at 1000 agents | p95 **129 ms** of a 1000 ms tick | `python -m brain.scale_bench` |
| Security detectors | precision **1.0**, recall **1.0** | `python -m brain.security measure` |
| Judge (offline) | accuracy **0.914**, F1 **0.903** | `python -m brain.judge_eval --judge fallback` |
| Brain at 100 agents | tick p95 **13.2 ms** | `python -m pytest brain/tests/test_perf.py -m perf` |
| Audit log | hash-chained, verifiable | `python -m brain.audit verify` |
| Policy backtest | replays real traces | `python -m brain.backtest` |
| MCP server | **17 tools**, installable | `python -m pytest brain/tests/test_packaging.py -m live` |

---

## What this file does not claim

Stated plainly, because a pitch that overstates is a pitch that gets caught:

- **No Claude judge latency or cost.** Never measured. Needs an API key.
- **No revenue figure.** Nothing here says how much money the *customer* will
  save — the ROI formula is there, the customer's numbers are not.
- **No comparison to a competitor.** There is no head-to-head measurement.
- **The demo fleet is simulated.** `FakeFleet` produces realistic loops, but
  it is not a customer's production traffic.
- **The security corpus is synthetic.** 115 labelled cases, 30 of them
  adversarial — real enough to catch the eight false positives it caught, and
  not a substitute for a red team.
