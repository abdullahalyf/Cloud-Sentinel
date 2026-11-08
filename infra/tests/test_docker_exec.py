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
    c = client.containers.run("alpine:3.20", "sleep 60", detach=True, name="cs-test-agent",
                              labels={"cloudsentinel.monitor": "true", "cloudsentinel.agent_id": "cs-test"})
    try:
        ex = DockerExecutor(replace(settings, executor="docker"))

        # 1. Container appears in list_agents
        agents = ex.list_agents()
        agent = next((r for r in agents if r.agent_id == "cs-test"), None)
        assert agent is not None
        assert agent.status == "running"
        assert agent.runtime == "docker"

        # 2. Pause
        res_pause = ex.pause("cs-test")
        assert res_pause.ok
        agent_paused = next((r for r in ex.list_agents() if r.agent_id == "cs-test"), None)
        assert agent_paused is not None
        assert agent_paused.status == "paused"

        # 3. Resume
        res_resume = ex.resume("cs-test")
        assert res_resume.ok
        agent_resumed = next((r for r in ex.list_agents() if r.agent_id == "cs-test"), None)
        assert agent_resumed is not None
        assert agent_resumed.status == "running"

        # 4. Go rogue
        res_rogue = ex.go_rogue("cs-test", "paraphrase_loop")
        assert res_rogue.ok

        # 5. Kill
        res_kill = ex.kill("cs-test")
        assert res_kill.ok

        # 6. Restart works for exited container
        res_restart = ex.restart("cs-test")
        assert res_restart.ok

        # 7. Unknown agents return ExecResult(False, ...) and never raise
        assert not ex.pause("nobody").ok
        assert not ex.resume("nobody").ok
        assert not ex.kill("nobody").ok
        assert not ex.restart("nobody").ok
        assert not ex.go_rogue("nobody", "loop").ok
    finally:
        c.remove(force=True)
