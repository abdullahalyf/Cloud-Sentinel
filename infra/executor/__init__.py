"""
Executors: the only code that touches Docker / Kubernetes (CONTRACTS §9).   Owner: Taseen.
The brain gets one through get_executor(settings). The fake one lives in shared/mocks/fake_fleet.py.
"""
from __future__ import annotations

from shared.config import Settings
from shared.contracts import Executor


def get_executor(cfg: Settings) -> Executor:
    if cfg.executor == "docker":
        from infra.executor.docker_exec import DockerExecutor

        return DockerExecutor(cfg)
    if cfg.executor == "k8s":
        from infra.executor.k8s_exec import K8sExecutor

        return K8sExecutor(cfg)
    raise ValueError(f"unknown EXECUTOR={cfg.executor!r} (use docker, k8s, or python -m brain --fake)")
