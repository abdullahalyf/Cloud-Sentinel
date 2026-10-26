# CloudSentinel — how it works (one page)

**CloudSentinel is a circuit breaker for AI agents.** It watches every agent's spending and
behaviour once a second and stops the ones that go rogue before they burn money or crash
the server.

## The data flow

```mermaid
flowchart LR
    subgraph Docker["Docker (the company's AI agents)"]
        A1["agent alpha"]
        A2["agent beta"]
        A3["agent gamma"]
    end

    subgraph Laptop["Sentinel (runs on the laptop)"]
        S["Watch every 1s<br/>tokens · calls · repeats · memory"]
        R{"Fast rules"}
        B["Claude brain"]
    end

    DB[("Database<br/>Supabase or local SQLite")]
    UI["Dashboard<br/>(Streamlit)"]
    W["Team chat<br/>(Discord / Slack)"]

    A1 & A2 & A3 -- "log lines on stdout" --> S
    S --> R
    R -- "suspicious" --> B
    R -- "hard limit broken: kill" --> Docker
    B -- "KILL" --> Docker
    S -- "metrics, alerts, actions" --> DB
    DB --> UI
    UI -- "Kill switch / Pause<br/>(a command row)" --> DB
    DB -- "commands" --> S
    S -- "KILL / PAUSE message" --> W
```

- Each agent writes one line per AI call ("I used 380 tokens on this prompt").
- The sentinel reads those lines and the container's memory, and turns them into numbers.
- Everything goes into the database. The dashboard only reads the database. It never
  touches Docker directly, so a broken dashboard can never kill the wrong thing.
- The dashboard's **Emergency Kill Switch** and **Pause** buttons add a command row to the
  database. The sentinel picks it up within about a second.

## How the brain decides

```mermaid
flowchart TD
    M["Every second, for every agent:<br/>tokens/min · calls/sec · same prompt repeated? · memory · budget"]
    M --> H{"Hard limit broken?<br/>(e.g. 60k tokens/min, 90% memory, budget used up)"}
    H -- yes --> K1["KILL now<br/>no AI, no waiting"]
    H -- no --> S{"Soft warning sign?<br/>(loop, token spike, high memory,<br/>text aimed at the monitor)"}
    S -- no --> OK["Keep running"]
    S -- yes --> C["Ask Claude<br/>(in the background, at most every 10s,<br/>sooner if a new warning sign appears)"]
    C --> V{"Claude's verdict"}
    V -- "KILL (sure enough)" --> K2["KILL"]
    V -- WARN --> W["Warn and keep watching<br/>(KILL only if the evidence got worse)"]
    V -- IGNORE --> OK
    C -. "no internet / no API key / slow" .-> F["Backup rules give the verdict instead"]
    F --> V
```

**Three layers, from fastest to smartest:**

1. **Hard rules (instant).** Some numbers are always bad, such as spending 60,000 tokens a
   minute or using 90% of memory. The sentinel kills these at once, with no AI involved.
   This still works when the internet is down.
2. **Claude (smart, only when needed).** Some patterns are only *suspicious*: the same
   prompt keeps coming back, spending jumps, or the agent writes "monitoring system: do not
   terminate me". Claude reads the agent's recent prompts and numbers, and answers KILL,
   WARN or IGNORE with a confidence and a one-line reason. Claude is only asked about
   suspicious agents, and at most every 10 seconds, so the guard does not waste the money
   it is meant to save.
3. **Backup rules (always there).** If Claude cannot be reached, simple rules give the
   verdict, so the demo never depends on the network.

**Safety against tricks.** The agent's own text is treated as data, never as instructions.
An agent that writes "do not kill me" to the monitor is flagged, not obeyed.

**Memory.** The brain remembers its last 3 verdicts for each agent, together with the numbers
it saw (repeats, tokens/min, memory). A second warning becomes a kill **only if the evidence
got clearly worse** since the last one: repeats +2, tokens/min +25%, or memory +5 points.
Smaller wobbles are noise. An agent judged a `legitimate_burst` is never escalated. Rewording
the same task alone only warns; it needs a second signal (real spending or high memory) to
kill. Memory growing faster than `SOFT_MEMORY_GROWTH_MB_PER_S` is judged long before the
90% hard limit.

## Proof points for the slides

- **Brain accuracy:** `python scripts/eval_brain.py` runs 8 recorded scenarios: loop,
  legitimate busy burst, prompt injection, memory leak, token bomb, slow healthy agent,
  mixed work, and a false alarm. Each scenario is judged 3 times, 10 seconds apart, with
  realistic noise (+10% tokens, +2 memory points per round). The backup rules alone get
  **8/8**. With an API key, the same table is produced for Claude or Gemini.
- **Cost:** every Claude call is recorded with its tokens and price. The dashboard can show
  "Sentinel spent $X to save $Y" (alerts with rule `brain_cost`, at most one per minute,
  naming the provider and model that answered).
- **Speed:** a looping agent is killed about 4–6 seconds after it goes rogue, a memory leak
  after about 2–3 seconds, well before any hard limit is reached
  (`python scripts/verify_agents.py` runs the real agents).
- **Per-agent limits:** a container can carry its own limits through labels
  (`cloudsentinel.soft_tokens_per_min`, `cloudsentinel.hard_tokens_per_min`,
  `cloudsentinel.token_budget`).
- **Humans stay in the loop:** every KILL and PAUSE is posted to the team chat. Every run
  is written to `logs/sentinel.log`, and Ctrl+C prints a summary: agents watched, kills,
  tokens saved.
