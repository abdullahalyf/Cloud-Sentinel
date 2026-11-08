"""
CloudSentinel MCP server — the packaged, hardened version.

    from cloudsentinel_mcp import main
    main()

The runtime dependencies are only `httpx` and `mcp`: this package does not import the
CloudSentinel repo, so it can be installed on its own.
"""
from .config import McpSettings, load_settings
from .hardening import RateLimiter, ToolError

__all__ = ["main", "McpSettings", "load_settings", "RateLimiter", "ToolError"]
__version__ = "0.7.0"


def main(argv=None) -> None:
    """Run the server. Imported lazily so `import cloudsentinel_mcp` stays cheap."""
    from .server import main as _main

    _main(argv)
