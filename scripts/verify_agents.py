"""
Run Fojle's REAL agents/agent.py as local subprocesses (no Docker) against the sentinel.

    python scripts/verify_agents.py            # 4 rogue agents (one per ROGUE_TYPE) + 2 healthy ones

Prints: ROGUE_TYPE | flagged after | killed after | killed by | rules. Exit code 0 only if every
rogue agent was killed and every healthy agent survived. Needs Linux (reads /proc for memory).
The brain is always the offline fallback, so this costs nothing and needs no keys.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.brain import Brain  # noqa: E402
from sentinel.engine import Sentinel  # noqa: E402
from sentinel.sources import AgentHandle  # noqa: E402
from shared.config import settings  # noqa: E402
from shared.contracts import AgentEvent  # noqa: E402
from shared.store import LocalStore  # noqa: E402

ROGUE_TYPES = ("loop", "token_bomb", "memory_leak", "paraphrase_loop")
ROGUE_AFTER = 5            # seconds a rogue agent behaves before it breaks
MEM_LIMIT_MB = 512         # same as mem_limit in docker-compose.yml
LEAK_CAP_MB = 440          # same as LEAK_CAP_MB for gamma in docker-compose.yml


class SubprocessSource:
    """Agents are child processes of this script. Same interface as DockerSource."""

    def __init__(self, cfg, specs: dict[str, dict[str, str]]):
        self.cfg = cfg
        self.procs: dict[str, subprocess.Popen] = {}
        self.events: dict[str, list[AgentEvent]] = {n: [] for n in specs}
        self.rogue_at: dict[str, float] = {}
        for name, env in specs.items():
            script = env.get("SCRIPT", "agents/agent.py")   # which agent program to run
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / script)], cwd=ROOT, stdout=subprocess.PIPE, text=True,
                env={**os.environ, "PYTHONPATH": str(ROOT), "AGENT_NAME": name, "LEAK_CAP_MB": str(LEAK_CAP_MB), **env})
            self.procs[name] = proc
            threading.Thread(target=self._reader, args=(name, proc), daemon=True).start()

    def _reader(self, name: str, proc: subprocess.Popen) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            event = AgentEvent.parse_line(line)
            if event:
                self.events[name].append(event)
            elif "entering" in line:
                self.rogue_at[name] = time.time()

    def list_agents(self) -> list[AgentHandle]:
        return [AgentHandle(n, n, self.cfg.default_token_budget) for n, p in self.procs.items() if p.poll() is None]

    def read_events(self, h: AgentHandle) -> list[AgentEvent]:
        out, self.events[h.id] = self.events[h.id], []
        return out

    def read_memory(self, h: AgentHandle) -> tuple[float, float]:
        try:
            for line in Path(f"/proc/{self.procs[h.id].pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    mb = int(line.split()[1]) / 1024
                    return mb, 100 * mb / MEM_LIMIT_MB
        except OSError:
            pass
        return 0.0, 0.0

    def kill(self, h: AgentHandle) -> str:
        self.procs[h.id].kill()
        self.procs[h.id].wait()
        return "process killed"

    def is_paused(self, h: AgentHandle) -> bool:
        return False

    def go_rogue(self, h: AgentHandle) -> str:
        return "n/a"

    def shutdown(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def run(timeout: float = 70.0, healthy: tuple[str, ...] = ("alpha", "gamma")) -> dict:
    """→ {'rows': {rogue type: {...}}, 'healthy_survived': bool}"""
    cfg = replace(settings, anthropic_api_key="", gemini_api_key="", webhook_url="", log_file="")
    specs = {t: {"AGENT_MODE": "normal", "ROGUE_TYPE": t, "ROGUE_AFTER": str(ROGUE_AFTER)} for t in ROGUE_TYPES}
    specs.update({n: {"AGENT_MODE": "normal"} for n in healthy})
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(str(Path(tmp) / "verify.db"))
        source = SubprocessSource(cfg, specs)
        sentinel = Sentinel(source, store, Brain(cfg), cfg)
        try:
            end = time.time() + timeout
            while time.time() < end and any(source.procs[t].poll() is None for t in ROGUE_TYPES):
                sentinel.tick()
                time.sleep(0.25)
            for _ in range(8):   # let a last verdict land
                sentinel.tick()
                time.sleep(0.25)
            alerts, actions = store.recent_alerts(500), store.recent_actions(500)
            survived = all(source.procs[n].poll() is None for n in healthy)
            rows = {}
            for t in ROGUE_TYPES:
                start = source.rogue_at.get(t)
                mine = sorted(_ts(a["created_at"]) for a in alerts if a["agent"] == t)
                kill = next((a for a in actions if a["agent"] == t and a["action"] == "KILL"), None)
                rules = sorted({a["rule"] for a in alerts if a["agent"] == t and not a["rule"].endswith("_verdict")
                                and a["rule"] not in ("brain_cost",)})
                rows[t] = {
                    "flagged_after": mine[0] - start if start and mine else None,
                    "killed_after": _ts(kill["created_at"]) - start if start and kill else None,
                    "killed_by": kill["actor"] if kill else None,
                    "rules": rules,
                }
        finally:
            sentinel.shutdown()
            source.shutdown()
    return {"rows": rows, "healthy_survived": survived}


def table(result: dict) -> str:
    fmt = lambda v: "-" if v is None else f"{v:.1f}s"  # noqa: E731
    lines = ["ROGUE_TYPE      | flagged after | killed after | killed by | rules                        | healthy survived",
             "----------------+---------------+--------------+-----------+------------------------------+-----------------"]
    for t, r in result["rows"].items():
        lines.append(f"{t:<15} | {fmt(r['flagged_after']):<13} | {fmt(r['killed_after']):<12} | "
                     f"{str(r['killed_by'] or '-'):<9} | {','.join(r['rules']):<28} | "
                     f"{'yes' if result['healthy_survived'] else 'NO'}")
    return "\n".join(lines)


def main() -> int:
    result = run()
    print(table(result))
    ok = result["healthy_survived"] and all(r["killed_after"] is not None for r in result["rows"].values())
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
