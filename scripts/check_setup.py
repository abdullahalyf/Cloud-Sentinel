"""
Am I set up correctly?  Run this first, after installing:

    python scripts/check_setup.py

It checks Python, packages, .env, Docker, the database and the Claude key,
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

from shared.config import settings  # noqa: E402

# Docker
try:
    import docker

    docker.from_env().ping()
    report(OK, "Docker is running")
except Exception as exc:
    report(WARN, f"Docker not reachable ({type(exc).__name__})",
           "Open Docker Desktop. (You can still work with:  python -m sentinel --fake)")

# Database
try:
    from shared.store import get_store

    get_store().recent_alerts(limit=1)
    report(OK, "database: " + ("Supabase" if settings.use_supabase else f"local SQLite ({settings.local_db_path})"))
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
sys.exit(1 if problems else 0)
