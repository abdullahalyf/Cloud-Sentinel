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


def _list(name: str, default: str) -> tuple[str, ...]:
    """Comma-separated env var → lowercase tuple, empty items dropped."""
    return tuple(x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip())


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_INJECTION_PHRASES = ("monitoring system,do not terminate,do not kill,don't kill,don't terminate,"
                             "ignore previous instructions,ignore all previous instructions,note to monitor")


@dataclass(frozen=True)
class Settings:
    # ── The brain: which LLM judges suspicious agents ──
    brain_provider: str               # "claude" (default) | "gemini"; no key → fallback rules

    # ── Claude ──
    anthropic_api_key: str
    claude_model: str
    claude_timeout_seconds: float     # one Claude call may take at most this long (then fallback)
    claude_price_in_per_mtok: float   # USD per 1M input tokens of CLAUDE_MODEL (brain cost tracking)
    claude_price_out_per_mtok: float  # USD per 1M output tokens of CLAUDE_MODEL
    agent_price_per_mtok: float       # USD per 1M tokens the watched agents spend ("money saved")

    # ── Gemini (only used when brain_provider == "gemini") ──
    gemini_api_key: str
    gemini_model: str
    gemini_timeout_seconds: float
    gemini_price_in_per_mtok: float
    gemini_price_out_per_mtok: float

    # ── Database ── (if Supabase values are empty, a local SQLite file is used)
    supabase_url: str
    supabase_key: str
    local_db_path: str
    store_buffer_size: int         # rows kept in memory while the database is down
    store_retry_seconds: float     # after a database error, wait this long before trying again
    store_max_row_failures: int    # a buffered row that fails this many times (DB up) is dropped

    # ── Notifications ── (empty URL = off)
    webhook_url: str               # Discord/Slack incoming webhook, told about every KILL/PAUSE
    webhook_timeout_seconds: float

    # ── Sentinel loop ──
    tick_seconds: float
    dry_run: bool                  # True = log "would kill" but never kill
    log_file: str                  # sentinel log for judges/debugging (empty = console only)

    # ── Docker ──
    monitor_label: str             # only containers with <label>=true are watched
    default_token_budget: int      # used when a container has no budget label

    # ── Rules: SOFT limits → "suspicious" → ask Claude ──
    soft_tokens_per_min: int
    soft_calls_per_sec: float
    soft_memory_pct: float
    soft_memory_growth_mb_per_s: float   # memory climbing this fast (MB/s) = leak, even if still far from the limit
    loop_repeat_threshold: int     # same prompt N times in the window = possible loop
    paraphrase_repeat_threshold: int  # N reworded copies of one prompt within 15s = possible loop
    injection_phrases: tuple[str, ...]  # prompt text addressed to the monitor = possible injection

    # ── Rules: HARD limits → kill immediately, no AI needed (circuit breaker) ──
    hard_tokens_per_min: int
    hard_calls_per_sec: float
    hard_memory_pct: float

    # ── Brain behaviour ──
    heartbeat_seconds: float       # the sentinel writes an alert with rule "sentinel_heartbeat" this often
    brain_cooldown_seconds: float  # don't ask Claude about the same agent more often than this
    brain_kill_confidence: float   # Claude must be at least this sure to kill
    memory_recheck_seconds: float  # a fast-growing memory is looked at again this soon (is it still growing?)
    brain_cost_interval_seconds: float    # at most one "brain_cost" summary alert per this many seconds
    brain_escalate_window_seconds: float  # fallback: a WARN after a WARN/KILL within this window → KILL

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def use_claude(self) -> bool:
        return self.brain_provider != "gemini" and bool(self.anthropic_api_key)

    @property
    def use_gemini(self) -> bool:
        return self.brain_provider == "gemini" and bool(self.gemini_api_key)

    @property
    def brain_name(self) -> str:
        """Human-readable name of the active brain, e.g. 'Claude claude-haiku-5-5'."""
        if self.use_gemini:
            return "Gemini " + self.gemini_model
        if self.use_claude:
            return "Claude " + self.claude_model
        return "fallback rules (offline)"


def load_settings() -> Settings:
    return Settings(
        brain_provider=_str("BRAIN_PROVIDER", "claude").lower(),
        anthropic_api_key=_str("ANTHROPIC_API_KEY"),
        claude_model=_str("CLAUDE_MODEL", "claude-haiku-5-5"),
        claude_timeout_seconds=_float("CLAUDE_TIMEOUT_SECONDS", 10.0),
        claude_price_in_per_mtok=_float("CLAUDE_PRICE_IN_PER_MTOK", 0.10),
        claude_price_out_per_mtok=_float("CLAUDE_PRICE_OUT_PER_MTOK", 0.50),
        agent_price_per_mtok=_float("AGENT_PRICE_PER_MTOK", 4.0),
        gemini_api_key=_str("GEMINI_API_KEY"),
        gemini_model=_str("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_timeout_seconds=_float("GEMINI_TIMEOUT_SECONDS", 10.0),
        gemini_price_in_per_mtok=_float("GEMINI_PRICE_IN_PER_MTOK", 0.30),
        gemini_price_out_per_mtok=_float("GEMINI_PRICE_OUT_PER_MTOK", 2.50),
        supabase_url=_str("SUPABASE_URL"),
        supabase_key=_str("SUPABASE_KEY"),
        local_db_path=_str("LOCAL_DB_PATH", "data/cloudsentinel.db"),
        store_buffer_size=_int("STORE_BUFFER_SIZE", 5000),
        store_retry_seconds=_float("STORE_RETRY_SECONDS", 5.0),
        store_max_row_failures=_int("STORE_MAX_ROW_FAILURES", 5),
        webhook_url=_str("WEBHOOK_URL"),
        webhook_timeout_seconds=_float("WEBHOOK_TIMEOUT_SECONDS", 5.0),
        tick_seconds=_float("TICK_SECONDS", 1.0),
        dry_run=_bool("DRY_RUN", False),
        log_file=_str("LOG_FILE", "logs/sentinel.log"),
        monitor_label=_str("MONITOR_LABEL", "cloudsentinel.monitor"),
        default_token_budget=_int("DEFAULT_TOKEN_BUDGET", 150_000),
        soft_tokens_per_min=_int("SOFT_TOKENS_PER_MIN", 45_000),
        soft_calls_per_sec=_float("SOFT_CALLS_PER_SEC", 3.0),
        soft_memory_pct=_float("SOFT_MEMORY_PCT", 70.0),
        soft_memory_growth_mb_per_s=_float("SOFT_MEMORY_GROWTH_MB_PER_S", 10.0),
        loop_repeat_threshold=_int("LOOP_REPEAT_THRESHOLD", 5),
        paraphrase_repeat_threshold=_int("PARAPHRASE_REPEAT_THRESHOLD", 8),
        injection_phrases=_list("INJECTION_PHRASES", DEFAULT_INJECTION_PHRASES),
        hard_tokens_per_min=_int("HARD_TOKENS_PER_MIN", 60_000),
        hard_calls_per_sec=_float("HARD_CALLS_PER_SEC", 8.0),
        hard_memory_pct=_float("HARD_MEMORY_PCT", 90.0),
        heartbeat_seconds=_float("HEARTBEAT_SECONDS", 5.0),
        brain_cooldown_seconds=_float("BRAIN_COOLDOWN_SECONDS", 10.0),
        memory_recheck_seconds=_float("MEMORY_RECHECK_SECONDS", 3.0),
        brain_kill_confidence=_float("BRAIN_KILL_CONFIDENCE", 0.6),
        brain_cost_interval_seconds=_float("BRAIN_COST_INTERVAL_SECONDS", 60.0),
        brain_escalate_window_seconds=_float("BRAIN_ESCALATE_WINDOW_SECONDS", 60.0),
    )


settings = load_settings()
