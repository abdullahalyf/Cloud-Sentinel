"""
All settings in one place, read from environment variables / the .env file (CONTRACTS §3).
Copy .env.example → .env and fill in your own values. Never commit .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from shared.console import use_utf8

# Windows consoles default to cp1252 and crash on the marks we print (✅, →, Bangla).
# Every tool imports shared.config, so switching here fixes them all at once.
use_utf8()

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # dotenv is optional
    pass


def _strip_comment(value) -> str:
    """
    Drop a trailing `# comment` from an env value.

    `.env.example` writes `CS_API_TOKEN=                    # set to require ...`.
    python-dotenv keeps that comment as the VALUE, so an unset setting silently
    becomes the comment text — and `CS_API_TOKEN` then demands a header equal to
    "# set to require header X-CS-Token on the C2 API", which locks out every
    legitimate client. An inline comment only counts when it is preceded by
    whitespace, so a value like `abc#def` stays intact.
    """
    text = str(value)
    head, sep, _ = text.partition("#")
    if sep and head and not head.endswith((" ", "\t")):
        # a `#` glued to a non-empty value is part of the value (`abc#def`)
        return text.strip()
    return head.strip()


def _str(name: str, default: str = "") -> str:
    return _strip_comment(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    try:
        return int(_strip_comment(os.getenv(name, default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_strip_comment(os.getenv(name, default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _strip_comment(os.getenv(name, str(default))).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # ── Judge ──
    anthropic_api_key: str
    judge_provider: str            # auto | claude | gemini | fallback
    claude_model: str
    gemini_api_key: str
    gemini_model: str
    # ── Database ──
    supabase_url: str
    supabase_key: str
    local_db_path: str
    # ── API / SDK / collector ──
    api_url: str
    api_token: str
    api_host: str
    api_port: int
    otlp_endpoint: str
    collector_port: int
    capture_prompts: bool
    policy_file: str
    # ── Runtime ──
    executor: str                  # docker | k8s | fake
    monitor_label: str
    k8s_namespace: str
    tick_seconds: float
    dry_run: bool
    default_budget_usd: float
    # ── Rules ──
    soft_tokens_per_min: int
    hard_tokens_per_min: int
    soft_calls_per_sec: float
    hard_calls_per_sec: float
    soft_memory_pct: float
    hard_memory_pct: float
    loop_repeat_threshold: int
    loop_score_threshold: float
    # ── Breaker / judge behaviour ──
    brain_cooldown_seconds: float
    brain_kill_confidence: float
    probation_seconds: float
    tool_approval_timeout_seconds: float
    roi_horizon_minutes: float
    # ── Auto-heal (A3): the judge proposes a patch, a confident one is applied ──
    autoheal: bool
    autoheal_min_confidence: float
    # ── Optional export to Arize Phoenix (collector forwards every OTLP batch) ──
    export_phoenix: bool = False
    phoenix_endpoint: str = "http://localhost:6006"
    phoenix_api_key: str = ""
    phoenix_project: str = "cloudsentinel"
    # ── Optional CloudWatch EMF export (collector writes JSON lines to a file; added 5 Nov, Fojle F10) ──
    export_cloudwatch: bool = False
    cloudwatch_file: str = "data/cloudwatch.jsonl"

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def judge(self) -> str:
        """Which judge will actually be used."""
        p = self.judge_provider
        if p == "auto":
            return "claude" if self.anthropic_api_key else ("gemini" if self.gemini_api_key else "fallback")
        return p


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=_str("ANTHROPIC_API_KEY"),
        judge_provider=_str("JUDGE_PROVIDER", "auto").lower(),
        claude_model=_str("CLAUDE_MODEL", "claude-haiku-5-5"),
        gemini_api_key=_str("GEMINI_API_KEY"),
        gemini_model=_str("GEMINI_MODEL", "gemini-2.5-flash"),
        supabase_url=_str("SUPABASE_URL"),
        supabase_key=_str("SUPABASE_KEY"),
        local_db_path=_str("LOCAL_DB_PATH", "data/cloudsentinel.db"),
        api_url=_str("CS_API_URL", "http://localhost:8000").rstrip("/"),
        api_token=_str("CS_API_TOKEN"),
        api_host=_str("CS_API_HOST", "0.0.0.0"),
        api_port=_int("CS_API_PORT", 8000),
        otlp_endpoint=_str("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/"),
        collector_port=_int("CS_COLLECTOR_PORT", 4318),
        capture_prompts=_bool("CS_CAPTURE_PROMPTS", True),
        policy_file=_str("CS_POLICY_FILE", "brain/policies.yaml"),
        executor=_str("EXECUTOR", "docker").lower(),
        monitor_label=_str("MONITOR_LABEL", "cloudsentinel.monitor"),
        k8s_namespace=_str("K8S_NAMESPACE", "cloudsentinel"),
        tick_seconds=_float("TICK_SECONDS", 1.0),
        dry_run=_bool("DRY_RUN", False),
        default_budget_usd=_float("DEFAULT_BUDGET_USD", 0.50),
        soft_tokens_per_min=_int("SOFT_TOKENS_PER_MIN", 25_000),
        hard_tokens_per_min=_int("HARD_TOKENS_PER_MIN", 60_000),
        soft_calls_per_sec=_float("SOFT_CALLS_PER_SEC", 2.0),
        hard_calls_per_sec=_float("HARD_CALLS_PER_SEC", 8.0),
        soft_memory_pct=_float("SOFT_MEMORY_PCT", 70.0),
        hard_memory_pct=_float("HARD_MEMORY_PCT", 90.0),
        loop_repeat_threshold=_int("LOOP_REPEAT_THRESHOLD", 8),
        loop_score_threshold=_float("LOOP_SCORE_THRESHOLD", 0.6),
        brain_cooldown_seconds=_float("BRAIN_COOLDOWN_SECONDS", 10.0),
        brain_kill_confidence=_float("BRAIN_KILL_CONFIDENCE", 0.6),
        probation_seconds=_float("PROBATION_SECONDS", 30.0),
        tool_approval_timeout_seconds=_float("TOOL_APPROVAL_TIMEOUT_SECONDS", 120.0),
        roi_horizon_minutes=_float("ROI_HORIZON_MINUTES", 60.0),
        autoheal=_bool("CS_AUTOHEAL", True),
        autoheal_min_confidence=_float("CS_AUTOHEAL_MIN_CONFIDENCE", 0.85),
        export_phoenix=_bool("CS_EXPORT_PHOENIX", False),
        phoenix_endpoint=_str("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006").rstrip("/"),
        phoenix_api_key=_str("PHOENIX_API_KEY"),
        phoenix_project=_str("PHOENIX_PROJECT_NAME", "cloudsentinel"),
        export_cloudwatch=_bool("CS_EXPORT_CLOUDWATCH", False),
        cloudwatch_file=_str("CS_CLOUDWATCH_FILE", "data/cloudwatch.jsonl"),
    )


settings = load_settings()
