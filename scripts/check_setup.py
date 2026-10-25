"""
Am I set up correctly?  Run this first, after installing:

    python scripts/check_setup.py

It checks Python, packages, .env, Docker (agent image, 3 labelled agents with a
memory limit), the database (and the 4 Supabase tables) and the Claude key,
and tells you in plain words what to fix.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
problems = 0


def report(status: str, what: str, hint: str = "") -> None:
    global problems
    if status == FAIL:
        problems += 1
    print(f"{status} {what}" + (f"\n     → {hint}" if hint else ""))


AGENT_IMAGE = "cloudsentinel-agent"     # image name from docker-compose.yml
EXPECTED_AGENTS = 3
TABLES = ("agent_metrics", "alerts", "actions", "commands")
Check = tuple[str, str, str]             # (status, what, one-line fix)


def check_agents(client, monitor_label: str) -> list[Check]:
    """Agent image built, 3 labelled containers running, each with a memory limit."""
    up = "Run:  docker compose up -d --build"
    try:
        client.images.get(AGENT_IMAGE)
        out = [(OK, f"agent image {AGENT_IMAGE} built", "")]
    except Exception:
        out = [(FAIL, f"agent image {AGENT_IMAGE} not built", up)]
    running = client.containers.list(filters={"label": f"{monitor_label}=true", "status": "running"})
    if len(running) >= EXPECTED_AGENTS:
        out.append((OK, f"{len(running)} agent containers running with {monitor_label}=true", ""))
    else:
        out.append((FAIL, f"only {len(running)} of {EXPECTED_AGENTS} agent containers running "
                          f"with {monitor_label}=true", "Run:  docker compose up -d --force-recreate"))
    for c in running:
        if (c.attrs.get("HostConfig") or {}).get("Memory"):
            out.append((OK, f"{c.name} has a memory limit", ""))
        else:
            out.append((FAIL, f"{c.name} has no memory limit (memory % can't be measured)",
                        "Add mem_limit: 512m in docker-compose.yml, then  docker compose up -d --force-recreate"))
    return out


def check_tables(store) -> list[Check]:
    """Each of the 4 Supabase tables answers a read through the store."""
    reads = {"agent_metrics": store.recent_metrics, "alerts": lambda: store.recent_alerts(limit=1),
             "actions": lambda: store.recent_actions(limit=1), "commands": store.pending_commands}
    out = []
    for table in TABLES:
        try:
            reads[table]()
            out.append((OK, f"Supabase table {table}", ""))
        except Exception as exc:
            out.append((FAIL, f"Supabase table {table} missing or unreadable ({type(exc).__name__})",
                        "Run db/schema.sql in the Supabase SQL editor"))
    return out


def main() -> int:
    print("\nCloudSentinel setup check\n" + "─" * 40)

    # Python
    if sys.version_info >= (3, 10):
        report(OK, f"Python {sys.version.split()[0]}")
    else:
        report(FAIL, f"Python {sys.version.split()[0]} is too old", "Install Python 3.11 or newer")

    # Packages
    for pkg in ["dotenv", "docker", "anthropic", "streamlit", "pandas", "supabase", "pytest"]:
        try:
            importlib.import_module(pkg)
            report(OK, f"package {pkg}")
        except ImportError:
            report(FAIL, f"package {pkg} missing", "Run:  pip install -r requirements.txt")

    # .env
    if (ROOT / ".env").exists():
        report(OK, ".env file found")
    else:
        report(WARN, "no .env file (defaults will be used)", "Copy .env.example to .env")

    from shared.config import settings

    # Docker
    try:
        import docker

        client = docker.from_env()
        client.ping()
        report(OK, "Docker is running")
        for check in check_agents(client, settings.monitor_label):
            report(*check)
    except Exception as exc:
        report(WARN, f"Docker not reachable ({type(exc).__name__})",
               "Open Docker Desktop. (You can still work with:  python -m sentinel --fake)")

    # Database
    try:
        from shared.store import get_store

        store = get_store()
        store.recent_alerts(limit=1)
        report(OK, "database: " + ("Supabase" if settings.use_supabase else f"local SQLite ({settings.local_db_path})"))
        if settings.use_supabase:
            for check in check_tables(store):
                report(*check)
    except Exception as exc:
        report(FAIL, f"database error: {exc}",
               "Check SUPABASE_URL / SUPABASE_KEY in .env, and that db/schema.sql was run in Supabase")

    # Claude
    if not settings.use_claude:
        report(WARN, "no ANTHROPIC_API_KEY — the brain will use the fallback rules",
               "Only Alif/Taseen need this. Others can ignore it.")
    else:
        try:
            import anthropic

            anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=15).messages.create(
                model=settings.claude_model, max_tokens=5, messages=[{"role": "user", "content": "ping"}])
            report(OK, f"Claude API works ({settings.claude_model})")
        except Exception as exc:
            report(FAIL, f"Claude API error: {exc}", "Check ANTHROPIC_API_KEY and CLAUDE_MODEL in .env")

    print("─" * 40)
    print("All good! 🎉" if problems == 0 else f"{problems} problem(s) to fix.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
