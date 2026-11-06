"""
DockerExecutor: pause / resume / kill / restart agent containers.   Owner: Taseen.

Only containers with label  cloudsentinel.monitor=true  are touched.
Agent id comes from label   cloudsentinel.agent_id  (falls back to the container name).
"""
from __future__ import annotations

import logging

from shared.config import Settings
from shared.contracts import ExecResult, RuntimeInfo

log = logging.getLogger("infra.docker")
AGENT_LABEL = "cloudsentinel.agent_id"


class DockerExecutor:
    def __init__(self, cfg: Settings):
        import docker  # only needed in docker mode

        self.client = docker.from_env()
        self.client.ping()  # fails fast with a clear error if Docker isn't running
        self.cfg = cfg

    def _containers(self) -> dict[str, object]:
        found = self.client.containers.list(all=True, filters={"label": f"{self.cfg.monitor_label}=true"})
        return {(c.labels or {}).get(AGENT_LABEL, c.name): c for c in found}

    def _get(self, agent_id: str):
        return self._containers().get(agent_id)

    @staticmethod
    def _memory(c) -> tuple[float, float]:
        try:
            stats = c.stats(stream=False, one_shot=True)
        except TypeError:  # older docker SDK
            stats = c.stats(stream=False)
        except Exception:
            return 0.0, 0.0
        mem = stats.get("memory_stats", {}) or {}
        inner = mem.get("stats", {}) or {}
        cache = inner.get("inactive_file", inner.get("total_inactive_file", inner.get("cache", 0)))
        used = max(mem.get("usage", 0) - cache, 0)
        limit = mem.get("limit") or 0
        return used / 1_048_576, (100.0 * used / limit if limit else 0.0)

    def list_agents(self) -> list[RuntimeInfo]:
        out = []
        for agent_id, c in self._containers().items():
            status = {"running": "running", "paused": "paused"}.get(c.status, "exited")
            mb, pct = self._memory(c) if status in ("running", "paused") else (0.0, 0.0)
            out.append(RuntimeInfo(agent_id, c.id[:12], "docker", status, round(mb, 1), round(pct, 1)))
        return out

    def _do(self, agent_id: str, verb: str, fn) -> ExecResult:
        c = self._get(agent_id)
        if c is None:
            return ExecResult(False, f"no container for agent {agent_id}")
        try:
            fn(c)
            return ExecResult(True, f"container {c.name} {verb}")
        except Exception as exc:  # docker.errors.APIError etc.
            return ExecResult(False, f"{verb} failed: {exc}")

    def pause(self, agent_id: str) -> ExecResult:
        return self._do(agent_id, "paused", lambda c: c.pause())

    def resume(self, agent_id: str) -> ExecResult:
        return self._do(agent_id, "resumed", lambda c: c.unpause())

    def kill(self, agent_id: str) -> ExecResult:
        def _kill(c):
            if c.status == "paused":
                c.unpause()
            c.kill()
        return self._do(agent_id, "killed", _kill)

    def restart(self, agent_id: str) -> ExecResult:
        return self._do(agent_id, "restarted", lambda c: c.start())

    def go_rogue(self, agent_id: str, kind: str) -> ExecResult:
        def _go_rogue(c):
            if c.status == "paused":
                c.unpause()
            c.exec_run(["sh", "-c", f"echo {kind} > /tmp/go_rogue"])
        return self._do(agent_id, f"switched to {kind}", _go_rogue)
