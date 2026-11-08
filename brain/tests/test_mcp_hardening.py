"""
A7 — MCP server hardening and packaging.

The acceptance criteria (docs/tasks/alif.md):
  * in a fresh venv, `pip install ./brain/mcp_pkg && cloudsentinel-mcp --help` works
  * an in-process stdio client lists the tools and calls list_agents against the mock
  * tests for the token requirement, read-only mode and the rate limit

The packaged server lives in brain/mcp_pkg/ and does not import shared/ — it only needs
httpx and mcp. These tests import it by path, so they test the same code the wheel ships.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "brain" / "mcp_pkg"


def _load(name: str, path: Path):
    """Import a module from the package directory by path (it is not installed in CI)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cs():
    """The packaged server, imported the way the wheel installs it."""
    if str(PKG) not in sys.path:
        sys.path.insert(0, str(PKG))
    import cloudsentinel_mcp  # noqa: F401  (the package is on the path now)
    from cloudsentinel_mcp import server

    return server


@pytest.fixture
def sdk_tool_error():
    """The SDK raises its own ToolError around a tool's failure — that is the class a
    caller sees, so that is the class the tests must catch."""
    from mcp.server.mcpserver.exceptions import ToolError

    return ToolError


@pytest.fixture
def mock_api_client(cs, monkeypatch):
    """Point the packaged server's client at the repo's mock API."""
    from fastapi.testclient import TestClient
    from shared.mocks import mock_api

    mock_api.seed()
    app = mock_api.app

    class _Client:
        def __init__(self, **kw):
            self._client = TestClient(app, headers=kw.get("headers") or {})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def request(self, method, path, json=None):
            return self._client.request(method, path, json=json)

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    yield
    mock_api.seed()


# ── the packaged server ──────────────────────────────────────────────────────
def test_the_package_has_the_right_shape():
    assert (PKG / "pyproject.toml").exists()
    assert (PKG / "README.md").exists()
    pyproject = (PKG / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "cloudsentinel-mcp"' in pyproject
    assert 'cloudsentinel-mcp = "cloudsentinel_mcp:main"' in pyproject
    # the package must not need the CloudSentinel repo
    assert "shared" not in pyproject.split("dependencies")[1].split("[project.optional")[0]


def test_the_package_only_imports_httpx_and_mcp():
    """A packaged server that imports `shared` cannot be installed on its own."""
    for path in (PKG / "cloudsentinel_mcp").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from shared" not in text, path
        assert "import shared" not in text, path


def test_the_wheel_builds_and_has_the_console_script(tmp_path):
    """The acceptance case: `pip install ./brain/mcp_pkg` gives a `cloudsentinel-mcp` command."""
    out = tmp_path / "wheel"
    result = subprocess.run([sys.executable, "-m", "pip", "wheel", str(PKG), "-w", str(out),
                             "--no-deps", "-q"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    wheels = list(out.glob("cloudsentinel_mcp-*.whl"))
    assert wheels, f"no wheel built: {list(out.iterdir())}"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        assert "cloudsentinel_mcp/server.py" in names
        assert "cloudsentinel_mcp/hardening.py" in names
        assert "cloudsentinel_mcp/config.py" in names
        assert any("entry_points.txt" in n for n in names)
        entry = zf.read([n for n in names if n.endswith("entry_points.txt")][0]).decode()
    assert "cloudsentinel-mcp" in entry and "cloudsentinel_mcp:main" in entry


# ── the tool surface ─────────────────────────────────────────────────────────
def test_the_annotations_are_audited(cs):
    """Every tool's readOnlyHint/destructiveHint must match what it actually does."""
    tools = {t.name: t for t in asyncio.run(cs.mcp.list_tools())}
    assert len(tools) == 17, sorted(tools)
    for name, tool in tools.items():
        destructive = name in cs.DESTRUCTIVE_TOOLS
        assert tool.annotations.destructive_hint == destructive, name
        assert tool.annotations.read_only_hint == (not destructive), name
    # the two sets must cover every tool — a tool in neither would be un-audited
    assert set(tools) == cs.DESTRUCTIVE_TOOLS | cs.READ_ONLY_TOOLS


def test_the_resources_and_the_prompt_exist(cs):
    resources = {str(r.uri) for r in asyncio.run(cs.mcp.list_resources())}
    assert "cloudsentinel://fleet" in resources
    templates = {t.uri_template for t in asyncio.run(cs.mcp.list_resource_templates())}
    assert "cloudsentinel://agents/{agent_id}" in templates
    prompts = {p.name for p in asyncio.run(cs.mcp.list_prompts())}
    assert "triage_fleet" in prompts


def test_an_in_process_client_lists_the_tools_and_calls_list_agents(cs, mock_api_client):
    """The acceptance case: an in-process stdio client lists the tools and calls list_agents."""
    tools = asyncio.run(cs.mcp.list_tools())
    assert {t.name for t in tools} >= {"list_agents", "pause_agent", "kill_agent"}

    agents = asyncio.run(cs.mcp.call_tool("list_agents", {}))
    payload = _tool_payload(agents)
    assert {a["agent_id"] for a in payload} >= {"alpha", "beta", "gamma", "delta"}


def _tool_payload(result) -> list:
    """The MCP call result carries the payload in `structured_content`."""
    if getattr(result, "structured_content", None):
        payload = result.structured_content
        return payload.get("result", payload) if isinstance(payload, dict) else payload
    content = result[0] if isinstance(result, tuple) else result
    if isinstance(content, list):
        text = "".join(getattr(c, "text", "") for c in content)
    else:
        text = getattr(content, "text", str(content))
    return json.loads(text)


# ── validation ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["", "   ", "a" * 65, "alpha/../beta", "alpha beta", "alpha;rm"])
def test_a_bad_agent_id_is_rejected(cs, bad):
    with pytest.raises(cs.ToolError):
        cs.check_agent_id(bad)


def test_a_good_agent_id_is_cleaned(cs):
    assert cs.check_agent_id("  alpha  ") == "alpha"


def test_a_missing_reason_is_rejected(cs):
    with pytest.raises(cs.ToolError, match="reason is required"):
        cs.check_reason("", required=True)


def test_an_over_long_reason_is_rejected(cs):
    with pytest.raises(cs.ToolError):
        cs.check_reason("x" * 501)


@pytest.mark.parametrize("value", ["maybe", "", "ALLOW!", 3])
def test_a_bad_decision_is_rejected(cs, value):
    with pytest.raises(cs.ToolError):
        cs.check_choice(value, ("allow", "deny", "rewrite"), "decision")


def test_a_good_decision_is_normalised(cs):
    assert cs.check_choice("DENY", ("allow", "deny"), "decision") == "deny"


def test_a_bad_budget_is_rejected(cs):
    with pytest.raises(cs.ToolError):
        cs.check_number(-1, "budget_usd")
    with pytest.raises(cs.ToolError):
        cs.check_number(float("nan"), "budget_usd")
    with pytest.raises(cs.ToolError):
        cs.check_number(float("inf"), "budget_usd")


def test_a_bad_memory_content_is_rejected(cs):
    with pytest.raises(cs.ToolError, match="JSON object"):
        cs.check_content("not a dict")
    with pytest.raises(cs.ToolError, match="at most"):
        cs.check_content({f"k{i}": "x" * 1000 for i in range(100)})


def test_a_bad_id_number_is_rejected(cs):
    with pytest.raises(cs.ToolError):
        cs.check_positive_id(0, "call_id")
    with pytest.raises(cs.ToolError):
        cs.check_positive_id(-3, "call_id")


def test_a_tool_error_carries_a_message_not_a_traceback(cs):
    """The model sees the message. The MCP layer turns ToolError into text."""
    error = cs.ToolError("agent_id must not be empty", "agent_id")
    assert "agent_id" in str(error)
    assert error.field == "agent_id"


# ── the rate limit ───────────────────────────────────────────────────────────
def test_the_rate_limit_stops_the_flood(cs):
    """30 destructive calls a minute, then it says no."""
    clock = [0.0]
    limiter = cs.RateLimiter(limit=3, window_seconds=60.0, clock=lambda: clock[0])
    for _ in range(3):
        allowed, _ = limiter.allow()
        assert allowed
    allowed, why = limiter.allow()
    assert not allowed
    assert "rate limit" in why.lower()
    # the window slides: after 61 seconds the calls are out of the window
    clock[0] = 61.0
    allowed, _ = limiter.allow()
    assert allowed


def test_the_rate_limit_counts_only_what_it_is_given(cs):
    clock = [0.0]
    limiter = cs.RateLimiter(limit=2, window_seconds=60.0, clock=lambda: clock[0])
    limiter.allow()
    assert limiter.remaining() == 1
    limiter.allow()
    assert limiter.remaining() == 0
    # one call ages out of the window, so one slot comes back
    clock[0] = 61.0
    assert limiter.remaining() == 2


def test_the_rate_limit_applies_to_writes_not_to_reads(cs, mock_api_client, monkeypatch, sdk_tool_error):
    """Reading the fleet must never be throttled — a dashboard should not be rate limited."""
    limiter = cs.RateLimiter(limit=1, window_seconds=60.0)
    monkeypatch.setattr(cs, "limiter", limiter)
    # five reads: they spend nothing from the limit
    for _ in range(5):
        asyncio.run(cs.mcp.call_tool("list_agents", {}))
    assert limiter.remaining() == 1
    # the first write fits in the limit
    asyncio.run(cs.mcp.call_tool("pause_agent", {"agent_id": "alpha", "reason": "first"}))
    # the second does not
    with pytest.raises(sdk_tool_error, match="rate limit"):
        asyncio.run(cs.mcp.call_tool("pause_agent", {"agent_id": "alpha", "reason": "flood"}))
    # but reads still work
    asyncio.run(cs.mcp.call_tool("list_agents", {}))


def test_a_write_beyond_the_limit_is_refused_before_the_api_is_called(cs, mock_api_client, monkeypatch,
                                                                    sdk_tool_error):
    limiter = cs.RateLimiter(limit=1, window_seconds=60.0)
    monkeypatch.setattr(cs, "limiter", limiter)
    asyncio.run(cs.mcp.call_tool("pause_agent", {"agent_id": "alpha", "reason": "first"}))
    with pytest.raises(sdk_tool_error, match="rate limit"):
        asyncio.run(cs.mcp.call_tool("pause_agent", {"agent_id": "beta", "reason": "second"}))


# ── read-only mode ───────────────────────────────────────────────────────────
def test_read_only_mode_hides_the_write_tools(cs):
    from cloudsentinel_mcp.hardening import read_only_tools, tool_is_allowed

    assert tool_is_allowed("pause_agent", True, cs.DESTRUCTIVE_TOOLS) is False
    assert tool_is_allowed("list_agents", True, cs.DESTRUCTIVE_TOOLS) is True
    assert read_only_tools(cs.DESTRUCTIVE_TOOLS | cs.READ_ONLY_TOOLS, cs.DESTRUCTIVE_TOOLS) == \
        sorted(cs.READ_ONLY_TOOLS)


def test_read_only_mode_refuses_a_write(cs, mock_api_client, monkeypatch, sdk_tool_error):
    monkeypatch.setattr(cs.settings, "readonly", True, raising=False)
    with pytest.raises(sdk_tool_error, match="read-only"):
        asyncio.run(cs.mcp.call_tool("pause_agent", {"agent_id": "alpha", "reason": "no"}))


def test_read_only_mode_still_allows_reads(cs, mock_api_client, monkeypatch):
    monkeypatch.setattr(cs.settings, "readonly", True, raising=False)
    result = asyncio.run(cs.mcp.call_tool("list_agents", {}))
    assert _tool_payload(result)


# ── the HTTP bind and the token ──────────────────────────────────────────────
def test_http_on_a_public_bind_without_a_token_refuses_to_start(cs):
    cfg = cs.load_settings.__wrapped__ if hasattr(cs.load_settings, "__wrapped__") else None
    from cloudsentinel_mcp.config import McpSettings

    public = McpSettings(api_url="http://localhost:8000", api_token="", readonly=False,
                         rate_limit_per_min=30, http_host="0.0.0.0", http_port=8765)
    with pytest.raises(SystemExit, match="refusing to serve"):
        cs._check_http_bind(public)


def test_http_on_a_public_bind_with_a_token_is_allowed(cs):
    from cloudsentinel_mcp.config import McpSettings

    public = McpSettings(api_url="http://localhost:8000", api_token="s3cret", readonly=False,
                         rate_limit_per_min=30, http_host="0.0.0.0", http_port=8765)
    cs._check_http_bind(public)  # must not raise


def test_http_on_a_local_bind_needs_no_token(cs):
    from cloudsentinel_mcp.config import McpSettings

    local = McpSettings(api_url="http://localhost:8000", api_token="", readonly=False,
                        rate_limit_per_min=30, http_host="127.0.0.1", http_port=8765)
    cs._check_http_bind(local)  # must not raise


def test_the_token_is_sent_as_both_headers(cs):
    from cloudsentinel_mcp.client import ApiClient

    client = ApiClient("http://localhost:8000", "s3cret")
    headers = client._headers()
    assert headers["X-CS-Token"] == "s3cret"
    assert headers["Authorization"] == "Bearer s3cret"
    # no token, no auth headers
    assert "Authorization" not in ApiClient("http://localhost:8000", "")._headers()


# ── the settings helper agrees with the repo's ──────────────────────────────
def test_the_package_and_the_repo_read_the_same_env_vars():
    """The package reads CS_API_URL / CS_API_TOKEN itself; the repo's shared/config.py must
    use the same names, or the two would disagree."""
    from cloudsentinel_mcp import config as pkg_config
    from shared.config import settings as repo_settings

    assert pkg_config.ENV_API_URL == "CS_API_URL"
    assert pkg_config.ENV_API_TOKEN == "CS_API_TOKEN"
    assert repo_settings.api_url  # the repo has one
    assert pkg_config.load_settings().api_url.endswith(repo_settings.api_url.rsplit(":", 1)[-1])
