"""
All settings in one place, read from environment variables / the .env file.
Copy .env.example → .env and fill in your own values. Never commit .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # dotenv is optional
    pass


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # ── Claude (the brain) ──
    anthropic_api_key: str
    claude_model: str

    # ── Database ── (if Supabase values are empty, a local SQLite file is used)
    supabase_url: str
    supabase_key: str
    local_db_path: str

    # ── Sentinel loop ──
    tick_seconds: float
    dry_run: bool                  # True = log "would kill" but never kill

    # ── Docker ──
    monitor_label: str             # only containers with <label>=true are watched
    default_token_budget: int      # used when a container has no budget label

    # ── Rules: SOFT limits → "suspicious" → ask Claude ──
    soft_tokens_per_min: int
    soft_calls_per_sec: float
    soft_memory_pct: float
    loop_repeat_threshold: int     # same prompt N times in the window = possible loop

    # ── Rules: HARD limits → kill immediately, no AI needed (circuit breaker) ──
    hard_tokens_per_min: int
    hard_calls_per_sec: float
    hard_memory_pct: float

    # ── Brain behaviour ──
    brain_cooldown_seconds: float  # don't ask Claude about the same agent more often than this
    brain_kill_confidence: float   # Claude must be at least this sure to kill
    brain_escalate_window_seconds: float  # fallback: a WARN after a WARN/KILL within this window → KILL

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def use_claude(self) -> bool:
        return bool(self.anthropic_api_key)


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=_str("ANTHROPIC_API_KEY"),
        claude_model=_str("CLAUDE_MODEL", "claude-haiku-5-5"),
        supabase_url=_str("SUPABASE_URL"),
        supabase_key=_str("SUPABASE_KEY"),
        local_db_path=_str("LOCAL_DB_PATH", "data/cloudsentinel.db"),
        tick_seconds=_float("TICK_SECONDS", 1.0),
        dry_run=_bool("DRY_RUN", False),
        monitor_label=_str("MONITOR_LABEL", "cloudsentinel.monitor"),
        default_token_budget=_int("DEFAULT_TOKEN_BUDGET", 150_000),
        soft_tokens_per_min=_int("SOFT_TOKENS_PER_MIN", 25_000),
        soft_calls_per_sec=_float("SOFT_CALLS_PER_SEC", 2.0),
        soft_memory_pct=_float("SOFT_MEMORY_PCT", 70.0),
        loop_repeat_threshold=_int("LOOP_REPEAT_THRESHOLD", 5),
        hard_tokens_per_min=_int("HARD_TOKENS_PER_MIN", 60_000),
        hard_calls_per_sec=_float("HARD_CALLS_PER_SEC", 8.0),
        hard_memory_pct=_float("HARD_MEMORY_PCT", 90.0),
        brain_cooldown_seconds=_float("BRAIN_COOLDOWN_SECONDS", 10.0),
        brain_kill_confidence=_float("BRAIN_KILL_CONFIDENCE", 0.6),
        brain_escalate_window_seconds=_float("BRAIN_ESCALATE_WINDOW_SECONDS", 60.0),
    )


settings = load_settings()
