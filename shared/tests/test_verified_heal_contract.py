"""
The contract test for B1's new setting: `CS_VERIFIED_HEAL`.

The setting is new behaviour, so it comes with a rule from Alif: **every new behaviour goes
behind a config flag, and the default is off unless it is fully tested.** The shadow dry-run
is new, so the default is off — with the flag off, every judge patch waits for a human,
which is exactly the A3 behaviour.

The test lives in `shared/tests/` because the setting lives in `shared/config.py`, which is
the contract.
"""
from __future__ import annotations

import os

from shared.config import load_settings


def _clear(monkeypatch):
    """Make sure the ambient environment cannot decide the test."""
    monkeypatch.delenv("CS_VERIFIED_HEAL", raising=False)


def test_the_verified_heal_flag_defaults_to_off(monkeypatch):
    """Off by default: a new behaviour that is not fully tested must not run by itself."""
    _clear(monkeypatch)
    assert load_settings().verified_heal is False


def test_the_verified_heal_flag_can_be_switched_on(monkeypatch):
    monkeypatch.setenv("CS_VERIFIED_HEAL", "true")
    assert load_settings().verified_heal is True


def test_the_verified_heal_flag_reads_the_usual_spellings(monkeypatch):
    for raw, want in (("1", True), ("yes", True), ("on", True), ("true", True),
                      ("0", False), ("no", False), ("off", False), ("false", False)):
        monkeypatch.setenv("CS_VERIFIED_HEAL", raw)
        assert load_settings().verified_heal is want


def test_the_verified_heal_flag_is_documented_in_the_env_example():
    """The .env.example is the settings' user interface. A setting nobody can find is a
    setting nobody can turn on."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / ".env.example"
    text = example.read_text(encoding="utf-8")
    assert "CS_VERIFIED_HEAL" in text, ".env.example must document CS_VERIFIED_HEAL"


def test_the_verified_heal_flag_is_documented_in_the_contracts():
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "CONTRACTS.md"
    text = doc.read_text(encoding="utf-8")
    assert "CS_VERIFIED_HEAL" in text, "docs/CONTRACTS.md §3 must document CS_VERIFIED_HEAL"
