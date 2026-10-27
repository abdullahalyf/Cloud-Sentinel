"""DockerSource against a mocked Docker client. No Docker needed."""
import time

from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.sources import DockerSource
from shared.config import load_settings
from shared.store import LocalStore

cfg = load_settings()
offline = cfg.__class__(**{**cfg.__dict__, "anthropic_api_key": ""})


class FakeContainer:
    def __init__(self, cid, name, stats_delay=0.0):
        self.id, self.name, self.status = cid, name, "running"
        self.labels = {"cloudsentinel.agent_name": name}
        self.stats_delay = stats_delay
        self.log_lines: list[str] = []
        self.logs_error: Exception | None = None
        self.stats_error: Exception | None = None
        self.killed = False

    def logs(self, **kw):
        if self.logs_error:
            raise self.logs_error
        return "\n".join(self.log_lines).encode()

    def stats(self, **kw):
        time.sleep(self.stats_delay)
        if self.stats_error:
            raise self.stats_error
        return {"memory_stats": {"usage": 100 * 1_048_576, "limit": 512 * 1_048_576, "stats": {}}}

    def kill(self):
        self.killed = True


class FakeClient:
    def __init__(self, containers):
        self.by_id = {c.id: c for c in containers}
        self.containers = self

    def list(self, **kw):
        return list(self.by_id.values())


def wait_for_memory(src, h, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        mb, _ = src.read_memory(h)
        if mb:
            return mb
        time.sleep(0.05)
    return 0.0


def test_slow_stats_do_not_slow_the_tick(tmp_path):
    containers = [FakeContainer(f"c{i}", n, stats_delay=1.5) for i, n in enumerate(("alpha", "beta", "gamma"))]
    src = DockerSource(cfg, client=FakeClient(containers))
    s = Sentinel(src, LocalStore(str(tmp_path / "t.db")), Brain(offline), cfg)
    started = time.time()
    s.tick()
    assert time.time() - started < 0.5   # 3 × 1.5s of stats would be 4.5s if read inline
    h = src.list_agents()[0]
    assert wait_for_memory(src, h) == 100.0   # the background read lands


def test_memory_read_never_blocks_and_keeps_one_read_in_flight():
    c = FakeContainer("c1", "alpha", stats_delay=0.5)
    src = DockerSource(cfg, client=FakeClient([c]))
    h = src.list_agents()[0]
    started = time.time()
    for _ in range(5):
        assert src.read_memory(h) == (0.0, 0.0)
    assert time.time() - started < 0.2
    assert len(src._memory_reads) == 1
