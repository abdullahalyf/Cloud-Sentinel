"""
K8sExecutor (stretch goal, Day 6).   Owner: Taseen. See docs/tasks/taseen.md Day 6 for the prompt.

Design: agents are Deployments labelled cloudsentinel.monitor=true, cloudsentinel.agent_id=<id>.
pause/kill = scale to 0 (memory lives in CloudSentinel, so resume loses nothing), resume/restart = scale to 1.
"""
from __future__ import annotations

from shared.config import Settings
from shared.contracts import ExecResult, RuntimeInfo


class K8sExecutor:
    def __init__(self, cfg: Settings):
        from kubernetes import client, config  # pip install kubernetes

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        self.apps = client.AppsV1Api()
        self.cfg = cfg

    def list_agents(self) -> list[RuntimeInfo]:
        raise NotImplementedError("Taseen Day 6")

    def pause(self, agent_id: str) -> ExecResult:
        raise NotImplementedError("Taseen Day 6")

    def resume(self, agent_id: str) -> ExecResult:
        raise NotImplementedError("Taseen Day 6")

    def kill(self, agent_id: str) -> ExecResult:
        raise NotImplementedError("Taseen Day 6")

    def restart(self, agent_id: str) -> ExecResult:
        raise NotImplementedError("Taseen Day 6")

    def go_rogue(self, agent_id: str, kind: str) -> ExecResult:
        raise NotImplementedError("Taseen Day 6")
