"""
Is my machine ready?   python scripts/check_setup.py
✅ ok · ⚠️ optional / works without it · ❌ must fix (the line below says how)
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
bad = 0


def ok(msg: str) -> None:
    print(f"✅ {msg}")


def warn(msg: str, fix: str) -> None:
    print(f"⚠️  {msg}\n     → {fix}")


def fail(msg: str, fix: str) -> None:
    global bad
    bad += 1
    print(f"❌ {msg}\n     → {fix}")


if sys.version_info >= (3, 11):
    ok(f"Python {sys.version.split()[0]}")
else:
    fail(f"Python {sys.version.split()[0]} is too old", "install Python 3.11+ from python.org")

for module, pkg in [("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("streamlit", "streamlit"), ("pandas", "pandas"),
                    ("httpx", "httpx"), ("yaml", "PyYAML"), ("opentelemetry.sdk", "opentelemetry-sdk"),
                    ("opentelemetry.proto", "opentelemetry-proto"), ("mcp.server.mcpserver", "mcp>=2"),
                    ("anthropic", "anthropic"), ("pytest", "pytest")]:
    try:
        importlib.import_module(module)
        ok(f"package {pkg}")
    except ImportError:
        fail(f"package {pkg} missing", "pip install -r requirements.txt")

if (ROOT / ".env").exists():
    ok(".env found")
else:
    warn("no .env file (defaults are used)", "copy .env.example .env   (Mac/Linux: cp .env.example .env)")

try:
    from shared.config import settings

    if settings.judge == "claude":
        ok(f"judge: Claude ({settings.claude_model})")
    elif settings.judge == "gemini":
        ok(f"judge: Gemini ({settings.gemini_model})")
    else:
        warn("judge: fallback rules (no ANTHROPIC_API_KEY)", "fine for development; Alif/Taseen add the key for demos")
    if settings.use_supabase:
        from shared.store import get_store

        get_store().recent_alerts(1)
        ok("database: Supabase")
    else:
        ok(f"database: local SQLite ({settings.local_db_path})")
except Exception as exc:  # noqa: BLE001
    fail(f"config/database problem: {exc}", "check SUPABASE_URL / SUPABASE_KEY in .env (or leave both empty)")

try:
    import docker

    docker.from_env().ping()
    ok("Docker is running")
except Exception:
    warn("Docker not available", "only needed for `docker compose up`; `python -m brain --fake` works without it")

print("\nAll good! Next: python -m brain --fake   and   streamlit run dashboard/app.py" if not bad
      else f"\n{bad} problem(s) to fix first.")
sys.exit(1 if bad else 0)
