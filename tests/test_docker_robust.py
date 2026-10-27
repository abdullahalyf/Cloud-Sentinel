"""DockerSource keeps the loop alive when containers vanish, restart or can't be read."""
from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.sources import DockerSource
from shared.store import LocalStore
from tests.test_docker_source import FakeClient, FakeContainer, cfg, offline


def line(ts, prompt):
    return (f'{ts} {{"cs": 1, "type": "llm_call", "agent": "alpha", "ts": 1.0, '
            f'"tokens_in": 10, "prompt": "{prompt}"}}')


def test_vanished_container_does_not_crash_the_loop(tmp_path):
    alpha, beta = FakeContainer("c1", "alpha"), FakeContainer("c2", "beta")
    client = FakeClient([alpha, beta])
    src = DockerSource(cfg, client=client)
    s = Sentinel(src, LocalStore(str(tmp_path / "t.db")), Brain(offline), cfg)
    s.tick()
    beta.logs_error = beta.stats_error = RuntimeError("404 No such container")
    s.tick()                                   # listed, but logs/stats fail: no exception
    del client.by_id["c2"]                     # now really gone
    s.tick()
    assert set(s.states) == {"c1"}
    assert "c2" not in src._last_log and "c2" not in src._memory


def test_unreadable_logs_return_no_events():
    c = FakeContainer("c1", "alpha")
    src = DockerSource(cfg, client=FakeClient([c]))
    h = src.list_agents()[0]
    c.logs_error = RuntimeError("logs unavailable")
    assert src.read_events(h) == []
    c.logs_error = None
    c.log_lines = ["garbage line", line("2026-10-25T12:00:00.000000001Z", "hi")]
    assert [e.prompt for e in src.read_events(h)] == ["hi"]


def test_restarted_container_keeps_reading_new_lines_only():
    c = FakeContainer("c1", "alpha")
    src = DockerSource(cfg, client=FakeClient([c]))
    h = src.list_agents()[0]
    c.log_lines = [line("2026-10-25T12:00:00.1Z", "first")]
    assert len(src.read_events(h)) == 1
    c.log_lines.append(line("2026-10-25T12:00:05.1Z", "after restart"))  # same id after `docker restart`
    assert [e.prompt for e in src.read_events(h)] == ["after restart"]


def test_recreated_container_gets_fresh_state(tmp_path):
    old = FakeContainer("old", "alpha")
    client = FakeClient([old])
    src = DockerSource(cfg, client=client)
    s = Sentinel(src, LocalStore(str(tmp_path / "t.db")), Brain(offline), cfg)
    s.tick()
    client.by_id = {"new": FakeContainer("new", "alpha")}   # docker compose --force-recreate
    s.tick()
    assert set(s.states) == {"new"}
    assert "old" not in src._last_log


def test_kill_of_missing_container_is_reported_not_raised(tmp_path):
    c = FakeContainer("c1", "alpha")
    src = DockerSource(cfg, client=FakeClient([c]))
    store = LocalStore(str(tmp_path / "t.db"))
    s = Sentinel(src, store, Brain(offline), cfg)
    h = src.list_agents()[0]
    src._containers.clear()                    # gone between list and kill
    assert s.kill(h, actor="human", reason="test") is False
    assert any(a["rule"] == "kill_failed" for a in store.recent_alerts())
