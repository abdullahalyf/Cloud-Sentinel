# CloudSentinel workspace rules (Google Antigravity)

Antigravity loads this file automatically (workspace rules folder `.agents/rules/`; older
versions used `.agent/rules/`). Antigravity also reads the root `AGENTS.md`. **That file
is the full rulebook. Read it first.** These are the rules that matter most:

1. **Never edit outside your owner's folder.** Taseen → `infra/`, `.github/`, `docker-compose.yml`,
   `docs/`, `README.md`, `AGENTS.md`, `.agents/`. Tamjid → `dashboard/`. If a change is needed
   elsewhere, stop and explain it in your final message instead of making it.
2. **Never change `shared/`** (contracts, config, store protocol, mocks) unless the task explicitly says so.
3. `dashboard/` talks to the system ONLY through `dashboard/api_client.py` (HTTP to the C2 API).
   Never import `shared.store`, `docker`, or anything from `brain/`.
4. Settings only via `shared.config.settings`. No hardcoded keys, URLs, ports or thresholds.
5. Never commit `.env`, keys, or `data/`.
6. It must still work offline: `python -m brain --fake` or `python -m shared.mocks.mock_api`.
7. No new frameworks or big dependencies (no React, no new DB). Use Python 3.11+, type hints and simple English comments.
8. Before finishing: run `python -m pytest -q` (everything must pass), and list every file you changed and how to test it by hand.
9. Do not run destructive commands (`git push --force`, `rm -rf`, `docker system prune`) unless the user asks for them.
