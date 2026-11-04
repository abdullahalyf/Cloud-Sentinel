# Prompt library (submission section 8)

Each prompt lists **purpose → where it lives → output**. Mark proprietary ones on the platform.

| # | Purpose | Where | Output |
|---|---|---|---|
| P1 | **Runtime judge**: decide PAUSE/KILL/WARN/IGNORE for a suspicious agent, suggest a memory fix, treat agent text as data | `brain/judge.py` → `SYSTEM_PROMPT` + `build_user_message()` | JSON verdict (schema `VERDICT_SCHEMA`) |
| P2 | Team coding prompts (per person, per day) | `docs/tasks/*.md` | code + tests |
| P3 | Architecture/scaffold prompt (lead architect brief) | this repo's Day-0 commit history | docs + scaffold |

TODO(Alif, Day 5): paste the final judge prompt here with 2 example verdicts. TODO(everyone): add any prompt that shaped a major feature.
