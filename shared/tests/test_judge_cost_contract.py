"""
The judge spend cap contract (CONTRACTS §3 — added 8 Nov, task A12).

The brain may call an LLM judge. That call costs money, and a brain watching a hundred
agents can make a lot of calls. `CS_JUDGE_MAX_USD_PER_HOUR` is the ceiling: above it the
brain stops calling the LLM and uses the deterministic fallback instead.

The setting is the contract. The cap's *behaviour* — what happens when it is hit, and the
alert that says so — is the brain's, and it is tested in `brain/tests/test_judge_cost.py`.
"""
from __future__ import annotations

import pytest

from shared.config import load_settings


# ── the settings ───────────────────────────────────────────────────────────
def test_the_cap_setting_has_a_default(monkeypatch):
    """No cap by default: the brain must not silently start refusing to judge."""
    monkeypatch.delenv("CS_JUDGE_MAX_USD_PER_HOUR", raising=False)
    assert load_settings().judge_max_usd_per_hour == 0.0


def test_the_cap_setting_reads_the_environment(monkeypatch):
    monkeypatch.setenv("CS_JUDGE_MAX_USD_PER_HOUR", "1.25")
    assert load_settings().judge_max_usd_per_hour == 1.25


def test_a_cap_of_zero_means_no_cap():
    """0 is the "no cap" value, so it must not be read as "no money ever"."""
    assert load_settings().judge_max_usd_per_hour == 0.0


def test_a_broken_cap_falls_back_to_no_cap(monkeypatch):
    """A typo in the environment must not take the brain down. The offline rule: the
    product still runs, it just does not enforce a ceiling it could not read."""
    monkeypatch.setenv("CS_JUDGE_MAX_USD_PER_HOUR", "not-a-number")
    assert load_settings().judge_max_usd_per_hour == 0.0


@pytest.mark.parametrize("value", ["0", "0.5", "10", "100.75"])
def test_the_cap_accepts_the_values_an_operator_would_write(monkeypatch, value: str):
    monkeypatch.setenv("CS_JUDGE_MAX_USD_PER_HOUR", value)
    assert load_settings().judge_max_usd_per_hour == float(value)


def test_a_negative_cap_is_treated_as_no_cap(monkeypatch):
    """A negative ceiling makes no sense, and treating it as "always capped" would stop
    the judge entirely. No cap is the safe reading."""
    monkeypatch.setenv("CS_JUDGE_MAX_USD_PER_HOUR", "-5")
    assert load_settings().judge_max_usd_per_hour == 0.0


# ── the docs ───────────────────────────────────────────────────────────────
def test_the_setting_is_in_the_environment_example():
    from pathlib import Path

    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "CS_JUDGE_MAX_USD_PER_HOUR" in example


def test_the_setting_is_in_the_contracts():
    from pathlib import Path

    contracts = (Path(__file__).resolve().parents[2] / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    assert "CS_JUDGE_MAX_USD_PER_HOUR" in contracts
