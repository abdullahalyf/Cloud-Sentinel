"""
The MCP server contract (CONTRACTS §7, added 8 Nov).

The MCP server is packaged on its own (`brain/mcp_pkg/`, installed as `cloudsentinel-mcp`)
and does not import `shared/`. It therefore reads the environment itself, and the two
readers must agree on the *names* — if they disagreed, an operator setting CS_MCP_READONLY
in `.env` would silently get a server that can still pause agents.

That agreement is what this file checks. The server's own behaviour (validation, the rate
limit, read-only mode, the HTTP bind) is tested in `brain/tests/test_mcp_hardening.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.config import load_settings

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "brain" / "mcp_pkg"

MCP_ENV_VARS = (
    "CS_MCP_READONLY",
    "CS_MCP_RATE_LIMIT",
    "CS_MCP_HTTP_HOST",
    "CS_MCP_HTTP_PORT",
)


# ── the settings exist and have the documented defaults ─────────────────────
def test_the_mcp_settings_exist(monkeypatch):
    for name in MCP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    cfg = load_settings()
    assert cfg.mcp_readonly is False
    assert cfg.mcp_rate_limit_per_min == 30
    assert cfg.mcp_http_host == "127.0.0.1"
    assert cfg.mcp_http_port == 8765


def test_the_mcp_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("CS_MCP_READONLY", "true")
    monkeypatch.setenv("CS_MCP_RATE_LIMIT", "5")
    monkeypatch.setenv("CS_MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("CS_MCP_HTTP_PORT", "9999")
    cfg = load_settings()
    assert cfg.mcp_readonly is True
    assert cfg.mcp_rate_limit_per_min == 5
    assert cfg.mcp_http_host == "0.0.0.0"
    assert cfg.mcp_http_port == 9999


@pytest.mark.parametrize("name", ["mcp_readonly", "mcp_rate_limit_per_min",
                                  "mcp_http_host", "mcp_http_port"])
def test_the_new_settings_have_a_default(name):
    """A missing env var must not break Settings (the dataclass has no default for it)."""
    assert hasattr(load_settings(), name)


# ── the repo and the package read the same names ───────────────────────────
def _pkg_config():
    """The packaged server's settings module — or skip.

    The contract branch lands *before* the brain branch, so the package may not exist
    yet when this runs in CI. The test then becomes live as soon as the brain branch
    merges, which is exactly when the agreement starts to matter.
    """
    import sys

    if not (PKG / "cloudsentinel_mcp" / "config.py").exists():
        pytest.skip("the packaged MCP server is not in the tree yet (it lands with A7)")
    if str(PKG) not in sys.path:
        sys.path.insert(0, str(PKG))
    from cloudsentinel_mcp import config as pkg_config

    return pkg_config


def test_the_package_and_the_repo_read_the_same_env_vars():
    """The package cannot import shared/, so it parses the environment itself. If the two
    disagree on a name, the operator's .env silently does nothing."""
    pkg_config = _pkg_config()

    assert pkg_config.ENV_READONLY == "CS_MCP_READONLY"
    assert pkg_config.ENV_RATE_LIMIT == "CS_MCP_RATE_LIMIT"
    assert pkg_config.ENV_HTTP_HOST == "CS_MCP_HTTP_HOST"
    assert pkg_config.ENV_HTTP_PORT == "CS_MCP_HTTP_PORT"
    # and the shared ones the server has always read
    assert pkg_config.ENV_API_URL == "CS_API_URL"
    assert pkg_config.ENV_API_TOKEN == "CS_API_TOKEN"


def test_the_package_reads_the_same_values_as_the_repo(monkeypatch):
    """Not just the names — the values. A different default would mean the repo says
    "read-only off" while the server says "read-only on"."""
    pkg_config = _pkg_config()

    monkeypatch.setenv("CS_MCP_READONLY", "true")
    monkeypatch.setenv("CS_MCP_RATE_LIMIT", "7")
    monkeypatch.setenv("CS_MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("CS_MCP_HTTP_PORT", "9100")

    repo = load_settings()
    pkg = pkg_config.load_settings()
    assert pkg.readonly == repo.mcp_readonly
    assert pkg.rate_limit_per_min == repo.mcp_rate_limit_per_min
    assert pkg.http_host == repo.mcp_http_host
    assert pkg.http_port == repo.mcp_http_port


# ── the documented names ────────────────────────────────────────────────────
def test_every_mcp_env_var_is_documented_in_the_contracts():
    """CONTRACTS §3 is the one place an operator looks. A setting that is not there does
    not exist as far as the operator is concerned."""
    contracts = (REPO / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    for name in MCP_ENV_VARS:
        assert f"`{name}`" in contracts, name


def test_every_mcp_env_var_is_in_the_env_example():
    """.env.example is what people copy. A setting missing from it is a setting nobody sets."""
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for name in MCP_ENV_VARS:
        assert re.search(rf"^{name}=", example, re.MULTILINE), name


def test_the_env_example_defaults_match_the_code():
    """The copy-paste file and the code must not drift apart."""
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    values = dict(re.findall(r"^(CS_MCP_\w+)=(.*)$", example, re.MULTILINE))
    # strip the inline comments the way shared/config.py does
    clean = {k: v.split("#")[0].strip() for k, v in values.items()}
    assert clean["CS_MCP_READONLY"] == "false"
    assert clean["CS_MCP_RATE_LIMIT"] == "30"
    assert clean["CS_MCP_HTTP_HOST"] == "127.0.0.1"
    assert clean["CS_MCP_HTTP_PORT"] == "8765"
