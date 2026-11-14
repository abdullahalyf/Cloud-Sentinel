"""
Demo helper: talks to the C2 API exactly like the dashboard does.

    python scripts/demo.py rogue beta paraphrase_loop   # kinds: loop paraphrase_loop token_bomb memory_leak bad_tool_call
    python scripts/demo.py pause|resume|kill|restart beta
    python scripts/demo.py fix beta                      # heal: fix beta's bad memory belief
    python scripts/demo.py reset                         # restart killed, resume paused, clear bad beliefs
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

API = os.getenv("CS_API_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.getenv("CS_API_TOKEN", "")


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"Content-Type": "application/json", "X-CS-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def command(agent: str, cmd: str, **params) -> None:
    call("POST", f"/v1/agents/{agent}/commands", {"command": cmd, "params": params, "requested_by": "terminal",
                                                  "reason": f"{cmd.lower()} from terminal"})
    print(f"{cmd} -> {agent} (runs within ~1 s)")


def fix(agent: str) -> None:
    call("PUT", f"/v1/agents/{agent}/memory", {"content": {"order_4471": "cancelled - skip it and move on"},
                                               "edited_by": "human", "reason": "demo fix"})
    print(f"memory of {agent} fixed")


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        sys.exit(1)
    verb = argv[0]
    if verb == "reset":
        for a in call("GET", "/v1/fleet")["agents"]:
            if a["state"] == "killed":
                command(a["agent_id"], "RESTART")
            elif a["state"] == "paused":
                command(a["agent_id"], "RESUME")
            call("PUT", f"/v1/agents/{a['agent_id']}/memory", {"content": {}, "edited_by": "human", "reason": "demo reset"})
        return
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)
    agent = argv[1]
    if verb == "rogue":
        command(agent, "GO_ROGUE", kind=argv[2] if len(argv) > 2 else "paraphrase_loop")
    elif verb == "fix":
        fix(agent)
    elif verb in ("pause", "resume", "kill", "restart"):
        command(agent, verb.upper())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
