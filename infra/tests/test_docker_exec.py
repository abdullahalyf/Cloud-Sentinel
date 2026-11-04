"""Runs only where Docker is available (skipped in CI without Docker and on laptops without it)."""
import pytest

docker = pytest.importorskip("docker")


def _docker_ok() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="Docker daemon not available")


def test_pause_resume_kill_restart():
    from dataclasses import replace

    from infra.executor.docker_exec import DockerExecutor
    from shared.config import settings

    client = docker.from_env()
    c = client.containers.run("alpine:3.20", "sleep 120", detach=True, name="cs-test-agent",
                              labels={"cloudsentinel.monitor": "true", "cloudsentinel.agent_id": "cs-test"})
    try:
        ex = DockerExecutor(replace(settings, executor="docker"))
        assert any(r.agent_id == "cs-test" for r in ex.list_agents())
        assert ex.pause("cs-test").ok and ex.resume("cs-test").ok
        assert ex.kill("cs-test").ok and ex.restart("cs-test").ok
        assert not ex.pause("nobody").ok
    finally:
        c.remove(force=True)
