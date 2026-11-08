# The 3 AM incident — a deterministic demo run

One command, one incident, no Docker and no API key. The clock is virtual, so the
numbers below are the same every time the runner is called with the same seed.

- **Runs**: 20
- **Held**: 20/20 runs passed every assertion
- **Agent**: `beta`
- **Root cause**: `loop_semantic` — `semantic_loop`
- **Rules that fired**: `loop_semantic`, `tool_cycle`
- **Action**: `PAUSE`
- **Healed**: yes

## The timings

| Step | Seconds | Budget |
|---|---|---|
| detect | 5.0s | 60s |
| judge | 1.0s | 60s |
| act | 0.0s | 30s |
| heal | 0.0s | 30s |
| total | 6.0s | — |

## The money

- **Saved**: $2.2344 (648,720 tokens)
- **Spent**: $0.0093

## The steps

- `1700000000` **rogue** — beta started looping
- `1700000005` **detect** — the brain flagged the agent
- `1700000006` **judge** — the judge reached a verdict
- `1700000006` **act** — the breaker acted
- `1700000006` **heal** — the agent was stopped and is waiting for a human

## The assertions

- every step held: the agent was detected, the judge decided, the breaker acted, and the money was counted.

## How to reproduce

```bash
python -m brain.demo_runner --runs 20 --write docs/research/demo_run.md
```

It exits non-zero if any step drifts over its budget, so it can be a CI job.
