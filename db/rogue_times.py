"""
db/rogue_times.py - measure how fast the sentinel kills each rogue type in REAL Docker.   Owner: Fojle.

It plays the dashboard's "Simulate rogue" button for one agent of each type, one after the other,
and times how long until the sentinel's KILL shows up in the database. Result: a markdown table.

Before you run it (3 terminals' worth of work, but only once):
  1. docker compose down
     docker compose -f docker-compose.scale.yml up -d --build      # 10 agents, 4 rogue types
  2. python -m sentinel                                              # in another terminal, leave it running
  3. python db/rogue_times.py --out docs/RESULTS.md --note "fallback rules, no API key"

  agent-01 = loop, agent-04 = token_bomb, agent-07 = memory_leak, agent-09 = paraphrase_loop
To run it again: docker compose -f docker-compose.scale.yml up -d --force-recreate
Needs the secret / service_role key (it writes a command row), like the sentinel.
It first checks that the sentinel is feeding THIS database and that every agent is fresh,
and stops with a clear message if not (use --skip-check to force it).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # so "from shared..." works when run as: python db/rogue_times.py
os.chdir(ROOT)                  # so .env and the local SQLite path resolve from the repo root

from shared.contracts import CommandRow  # noqa: E402
from shared.store import SupabaseStore, get_store  # noqa: E402

DEFAULT_AGENTS = {
    "agent-01": "loop",
    "agent-04": "token_bomb",
    "agent-07": "memory_leak",
    "agent-09": "paraphrase_loop",
}


def to_seconds(iso: str) -> float:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).timestamp()


def first_action(store, agent: str, kind: str, since: float) -> dict | None:
    """The oldest action of this kind for this agent that happened after `since`."""
    rows = [
        a for a in store.recent_actions(200)
        if a["agent"] == agent and a["action"] == kind and to_seconds(a["created_at"]) >= since
    ]
    return min(rows, key=lambda a: to_seconds(a["created_at"])) if rows else None


def preflight(store, agents: list[str]) -> list[str]:
    """What is wrong, if anything: no live data from an agent, or an agent that is not fresh."""
    latest = {}
    for row in store.recent_metrics(minutes=0.5):   # newest 30 seconds, oldest first
        latest[row["agent"]] = row
    problems = []
    for agent in agents:
        row = latest.get(agent)
        if row is None:
            problems.append(f"{agent}: no data in this database in the last 30 s")
        elif row["status"] != "running":
            problems.append(f"{agent}: status is '{row['status']}', it is not fresh")
    return problems


def measure(store, agent: str, timeout: float) -> dict:
    start = time.time()
    store.insert_command(CommandRow(agent, "GO_ROGUE", requested_by="rogue_times"))
    while time.time() - start < timeout:
        kill = first_action(store, agent, "KILL", start)
        if kill:
            return {"killed": True, "seconds": to_seconds(kill["created_at"]) - start,
                    "actor": kill["actor"], "reason": kill["reason"]}
        time.sleep(0.5)
    warn = first_action(store, agent, "WARN", start)
    return {"killed": False, "seconds": timeout, "actor": warn["actor"] if warn else "-",
            "reason": warn["reason"] if warn else "no reaction at all"}


def table(results: list[tuple[str, str, dict]], timeout: float) -> str:
    lines = ["| Rogue type | Agent | Result | Decided by | Why |", "|---|---|---|---|---|"]
    for rogue_type, agent, r in results:
        outcome = f"killed after {r['seconds']:.1f} s" if r["killed"] else f"NOT killed in {timeout:.0f} s"
        why = r["reason"].replace("|", "/").replace("\n", " ")[:90]
        lines.append(f"| {rogue_type} | {agent} | {outcome} | {r['actor']} | {why} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Time the kill of each rogue type in real Docker.")
    parser.add_argument("--agents", nargs="*", help="agent names to test (default: agent-01 04 07 09)")
    parser.add_argument("--timeout", type=float, default=60, help="seconds to wait for a kill (default 60)")
    parser.add_argument("--gap", type=float, default=5, help="seconds to rest between agents (default 5)")
    parser.add_argument("--note", default="", help="what was running, e.g. 'fallback rules, no API key'")
    parser.add_argument("--out", help="append the table to this file, e.g. docs/RESULTS.md")
    parser.add_argument("--skip-check", action="store_true", help="do not check that the sentinel and agents are ready")
    args = parser.parse_args()

    targets = {a: DEFAULT_AGENTS.get(a, "?") for a in args.agents} if args.agents else DEFAULT_AGENTS
    store = get_store()
    print("Database:", "Supabase (SHARED by the whole team!)" if isinstance(store, SupabaseStore) else "local SQLite file")
    problems = [] if args.skip_check else preflight(store, list(targets))
    if problems:
        print("Not ready, nothing was sent:")
        for problem in problems:
            print("  -", problem)
        print("Check: 1) the sentinel is running, 2) it printed the SAME 'Database:' line as above,")
        print("       3) fresh agents: docker compose -f docker-compose.scale.yml up -d --force-recreate")
        return 1
    results = []
    for agent, rogue_type in targets.items():
        print(f"{agent} ({rogue_type}): sending GO_ROGUE, waiting up to {args.timeout:.0f} s ...", flush=True)
        r = measure(store, agent, args.timeout)
        print("   ->", f"killed after {r['seconds']:.1f} s by {r['actor']}" if r["killed"] else "NOT killed", flush=True)
        results.append((rogue_type, agent, r))
        time.sleep(args.gap)

    heading = f"## Rogue agents in real Docker ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    section = f"{heading}\n\n" + (f"Setup: {args.note}\n\n" if args.note else "") + table(results, args.timeout) + "\n"
    print("\n" + section)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        with path.open("a", encoding="utf-8") as f:
            f.write(("\n" if existed else "# Test results\n\n") + section)
        print(f"Appended to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())