"""
The prompt-injection contract (CONTRACTS §11a, added 8 Nov).

Agent text is data, never instructions. The contract fixes the vocabulary the brain and the
dashboard share: the two thresholds, the host allowlist and the `InjectionVerdict` shape.
"""
from __future__ import annotations

import pytest

from shared.contracts import ACTION_TYPES, PATTERNS, InjectionVerdict
from shared.config import load_settings


def test_the_injection_patterns_exist():
    """The judge may name both kinds of injection (a prompt and a tool argument)."""
    assert "prompt_injection" in PATTERNS
    assert "unsafe_tool_input" in PATTERNS


def test_a_denial_is_an_action_type():
    """A blocked tool call is something DONE, so it belongs in the actions table."""
    assert "TOOL_INJECTION_DENY" in ACTION_TYPES


def test_the_injection_settings_exist(monkeypatch):
    for name in ("CS_INJECTION_ENABLED", "CS_INJECTION_DENY_THRESHOLD",
                 "CS_INJECTION_APPROVAL_THRESHOLD", "CS_INJECTION_MEMORY_THRESHOLD",
                 "CS_INJECTION_ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    cfg = load_settings()
    assert cfg.injection_enabled is True
    assert cfg.injection_deny_threshold == 0.8
    assert cfg.injection_approval_threshold == 0.5
    assert cfg.injection_memory_threshold == 0.5
    assert "api.shopbd.com" in cfg.injection_allowed_hosts

    monkeypatch.setenv("CS_INJECTION_ENABLED", "false")
    monkeypatch.setenv("CS_INJECTION_DENY_THRESHOLD", "0.9")
    monkeypatch.setenv("CS_INJECTION_APPROVAL_THRESHOLD", "0.6")
    monkeypatch.setenv("CS_INJECTION_MEMORY_THRESHOLD", "0.7")
    monkeypatch.setenv("CS_INJECTION_ALLOWED_HOSTS", "example.com")
    cfg = load_settings()
    assert cfg.injection_enabled is False
    assert cfg.injection_deny_threshold == 0.9
    assert cfg.injection_approval_threshold == 0.6
    assert cfg.injection_memory_threshold == 0.7
    assert cfg.injection_allowed_hosts == "example.com"


@pytest.mark.parametrize("name", ["injection_enabled", "injection_deny_threshold",
                                  "injection_approval_threshold", "injection_memory_threshold",
                                  "injection_allowed_hosts"])
def test_the_new_settings_have_a_default(name):
    """A missing env var must not break Settings (the dataclass has no default for it)."""
    assert hasattr(load_settings(), name)


def test_the_thresholds_are_ordered():
    """The approval threshold must be below the deny threshold, or the gate has a dead band."""
    cfg = load_settings()
    assert cfg.injection_approval_threshold < cfg.injection_deny_threshold


def test_the_verdict_shape():
    """The verdict is what the gate, the judge and the dashboard all read."""
    v = InjectionVerdict(0.9, ["shell metacharacters in a non-shell tool"], ["shell_metachars"])
    assert v.hit is True
    assert v.to_dict() == {"score": 0.9, "reasons": ["shell metacharacters in a non-shell tool"],
                           "signals": ["shell_metachars"]}
    assert InjectionVerdict().hit is False
