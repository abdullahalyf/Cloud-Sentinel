"""
The MCP server's own settings — a tiny local copy, on purpose.

The packaged server (`pip install cloudsentinel-mcp`) must run with only `httpx` and `mcp`
installed. It cannot import `shared/` from the CloudSentinel repo, so it reads the same
environment variables itself. If `shared/config.py` ever changes these names, change them
here too — `brain/tests/test_mcp.py` checks that the two agree.

Nothing here reads a file: the packaged server has no idea where the repo is.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# The names this server understands. `shared/config.py` reads the same ones.
ENV_API_URL = "CS_API_URL"
ENV_API_TOKEN = "CS_API_TOKEN"
ENV_READONLY = "CS_MCP_READONLY"
ENV_RATE_LIMIT = "CS_MCP_RATE_LIMIT"
ENV_HTTP_HOST = "CS_MCP_HTTP_HOST"
ENV_HTTP_PORT = "CS_MCP_HTTP_PORT"

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_RATE_LIMIT = 30          # destructive calls per minute, per session
DEFAULT_HTTP_HOST = "127.0.0.1"


def _str(name: str, default: str = "") -> str:
    """Like shared.config._str: a trailing `# comment` after whitespace is not part of the value."""
    text = str(os.getenv(name, default))
    head, sep, _ = text.partition("#")
    if sep and head and not head.endswith((" ", "\t")):
        return text.strip()
    return head.strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    return _str(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass
class McpSettings:
    api_url: str
    api_token: str
    readonly: bool
    rate_limit_per_min: int
    http_host: str
    http_port: int

    @property
    def is_local_bind(self) -> bool:
        """True when the HTTP transport is only reachable from this machine."""
        return self.http_host in ("127.0.0.1", "::1", "localhost")


def load_settings() -> McpSettings:
    return McpSettings(
        api_url=_str(ENV_API_URL, DEFAULT_API_URL).rstrip("/"),
        api_token=_str(ENV_API_TOKEN),
        readonly=_bool(ENV_READONLY, False),
        rate_limit_per_min=_int(ENV_RATE_LIMIT, DEFAULT_RATE_LIMIT),
        http_host=_str(ENV_HTTP_HOST, DEFAULT_HTTP_HOST),
        http_port=_int(ENV_HTTP_PORT, 8765),
    )


settings = load_settings()
