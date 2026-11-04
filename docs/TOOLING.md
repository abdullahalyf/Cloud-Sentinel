# Tooling & IDE disclosure (submission section 6)

| Person | IDE / assistant | Rules / memory files |
|---|---|---|
| Alif | Claude Code, Codex | `AGENTS.md`, `CLAUDE.md` (if added) |
| Taseen | Google Antigravity | `AGENTS.md`, `.agents/rules/cloudsentinel.md` |
| Tamjid | Google Antigravity | `AGENTS.md`, `.agents/rules/cloudsentinel.md` |
| Fojle | Codex | `AGENTS.md` |
| Orin | Codex | `AGENTS.md` |

MCP: CloudSentinel **exposes** an MCP server (`brain/mcp_server.py`, 12 tools, CONTRACTS §7) used from Claude Desktop / Claude Code.
Models called at runtime: Claude Haiku 5.5 (judge), optional Gemini 2.5 Flash. Data: synthetic only.
