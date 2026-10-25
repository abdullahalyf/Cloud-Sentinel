from unittest.mock import Mock

import pytest

from sentinel.sources import DockerSource, FakeSource
from shared.config import load_settings


def test_fake_pause_freezes_events_without_resume_backlog(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('sentinel.sources.time.time', lambda: clock[0])
    source = FakeSource(load_settings(), names=('beta',), auto_rogue=None)
    h = source.list_agents()[0]
    source.go_rogue(h)
    source.read_events(h)
    calls = source.agents['beta'].calls
    source.pause(h)
    clock[0] += 3600
    source.pause(h)  # repeated pause must not reset its start time
    assert source.read_events(h) == []
    assert source.agents['beta'].calls == calls
    assert source.list_agents() == [h]
    source.resume(h)
    assert not source.is_paused(h)
    assert len(source.read_events(h)) <= 1
    clock[0] += 2
    assert source.read_events(h)
    assert source.agents['beta'].rogue_since == 3700


def test_fake_resume_is_idempotent(monkeypatch):
    source = FakeSource(load_settings(), auto_rogue=None)
    h = source.list_agents()[0]
    next_call = source.agents[h.name].next_call
    source.resume(h)
    assert source.agents[h.name].next_call == next_call


@pytest.fixture
def docker_source(monkeypatch):
    client = Mock()
    container = Mock(id='docker-beta', name='agent-beta', labels={}, status='running')
    client.containers.list.return_value = [container]
    monkeypatch.setattr('docker.from_env', lambda: client)
    source = DockerSource(load_settings())
    h = source.list_agents()[0]
    return source, h, container, client


def test_docker_pause_resume_and_paused_discovery(docker_source):
    source, h, container, client = docker_source
    source.pause(h)
    container.pause.assert_called_once_with()
    container.status = 'paused'
    source.pause(h)
    container.pause.assert_called_once_with()
    assert source.list_agents() == [h]
    assert client.containers.list.call_args.kwargs['filters']['status'] == ['running', 'paused']
    assert source.is_paused(h)
    source.resume(h)
    container.unpause.assert_called_once_with()
    container.status = 'running'
    source.resume(h)
    container.unpause.assert_called_once_with()


def test_docker_kill_unpauses_first(docker_source):
    source, h, container, _ = docker_source
    container.status = 'paused'
    source.kill(h)
    assert [call[0] for call in container.method_calls] == ['unpause', 'reload', 'kill']
