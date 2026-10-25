# AGENTS.md — rules for AI coding tools (Codex, AntiGravity, Puku, Claude…)

Read this whole file before changing anything in this repo.

## What this project is
CloudSentinel is a circuit breaker for AI agents running in Docker. It watches each agent's
token spend, call rate, repeated prompts (loops) and memory, and kills runaway containers.
Fast rules handle hard limits; Claude judges suspicious cases. A Streamlit dashboard shows
everything and has an Emergency Kill Switch.

## Architecture (data flow)
```
agents/agent.py (in Docker) --stdout JSON lines--> sentinel/ (on laptop)
sentinel/ --writes rows--> database (Supabase, or local SQLite fallback)
dashboard/ --reads rows--> database
dashboard/ --inserts CommandRow (KILL / GO_ROGUE)--> database --polled by--> sentinel/
```
The dashboard NEVER talks to Docker. The sentinel NEVER imports dashboard code.

## Folder ownership — only edit the folder of the task you were given
| Folder / file | Owner | Notes |
|---|---|---|
| `sentinel/` | Alif | engine, rules, Claude brain, Docker access |
| `shared/contracts.py` | Alif + Taseen | THE CONTRACT. Do not change without being told to. |
| `shared/config.py` | Alif | all settings come from `.env` |
| `shared/store.py`, `db/` | Fojle | database; both stores must keep identical methods |
| `agents/` | Fojle | simulated AI agents |
| `dashboard/` | Tamjid | Streamlit UI |
| `presentation/`, `docs/QA.md` | Orin | pitch + test checklist |
| `tests/` | everyone | add tests for what you change |
| `.github/`, merges | Taseen | leader |

## Hard rules
1. **Contracts first.** Data shapes live in `shared/contracts.py` and `db/schema.sql`.
   If a task seems to need a new field, STOP and say so in your summary instead of adding it.
2. Read data only via `shared.store.get_store()`. Never create your own Supabase/SQLite client.
3. Settings only via `shared.config.settings`. Never hardcode keys, URLs or thresholds.
4. Never commit `.env`, API keys, or `data/`.
5. Everything must still work offline: `python -m sentinel --fake` + local SQLite, no Docker, no keys.
6. Keep it simple — this is a hackathon. No new frameworks, no new databases, no async rewrites.
7. Python 3.11+, type hints, short functions, comments in English.
8. Before finishing: run `python -m pytest -q` and make sure everything passes.
9. In your final message, list every file you changed and how to test the change by hand.

## Commands
```bash
pip install -r requirements.txt
python scripts/check_setup.py            # is my machine ready?
python -m pytest -q                      # tests
python -m sentinel --fake                # sentinel with 3 simulated agents (beta goes rogue after 20s)
streamlit run dashboard/app.py           # dashboard (in a second terminal)
docker compose up -d --build             # real agent containers
python -m sentinel                       # sentinel watching real containers
python scripts/command.py rogue beta     # trigger the rogue agent
docker compose up -d --force-recreate    # reset after a demo
```
