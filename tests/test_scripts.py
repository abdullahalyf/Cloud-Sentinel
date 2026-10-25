"""check_setup.py and demo.py --docker with mocks. No Docker, no Supabase."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_setup = load("check_setup")
demo = load("demo")


class Images:
    def __init__(self, built):
        self.built = built

    def get(self, name):
        if not self.built:
            raise LookupError(name)


class Containers:
    def __init__(self, items):
        self.items, self.filters = items, None

    def list(self, filters=None, **kw):
        self.filters = filters
        return self.items


def container(name, memory=512 * 1024 * 1024):
    return SimpleNamespace(name=name, attrs={"HostConfig": {"Memory": memory}})


def docker_client(built=True, items=()):
    return SimpleNamespace(images=Images(built), containers=Containers(list(items)))


def statuses(checks):
    return [status for status, _, _ in checks]


def test_agents_all_good():
    client = docker_client(items=[container(n) for n in ("agent-alpha", "agent-beta", "agent-gamma")])
    checks = check_setup.check_agents(client, "cloudsentinel.monitor")
    assert set(statuses(checks)) == {check_setup.OK}
    assert client.containers.filters == {"label": "cloudsentinel.monitor=true", "status": "running"}


def test_agents_each_failure_has_a_one_line_fix():
    client = docker_client(built=False, items=[container("agent-alpha", memory=0)])
    checks = check_setup.check_agents(client, "cloudsentinel.monitor")
    fails = [c for c in checks if c[0] == check_setup.FAIL]
    assert len(fails) == 3                     # image, count, memory limit
    assert all(fix and "\n" not in fix for _, _, fix in fails)
    assert any("docker compose up -d --build" in fix for _, _, fix in fails)
    assert any("mem_limit" in fix for _, _, fix in fails)


def test_supabase_tables():
    def broken():
        raise RuntimeError("relation \"commands\" does not exist")

    store = SimpleNamespace(recent_metrics=lambda: [], recent_alerts=lambda limit: [],
                            recent_actions=lambda limit: [], pending_commands=broken)
    checks = check_setup.check_tables(store)
    assert statuses(checks) == [check_setup.OK] * 3 + [check_setup.FAIL]
    assert "commands" in checks[-1][1] and "db/schema.sql" in checks[-1][2]


class FakeChild:
    returncode = 0

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_demo_docker_mode_uses_real_sentinel_and_prints_reset(monkeypatch, capsys):
    seen = {}

    def popen(command, **kw):
        seen["command"] = command
        return FakeChild()

    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    monkeypatch.setattr(demo, "timeline", lambda store, child, timeout:
                        "rogue at 10.0s → flagged at 13.0s → killed at 16.0s by claude")
    monkeypatch.setitem(sys.modules, "shared.store", SimpleNamespace(get_store=lambda: "real-store"))
    assert demo.main(["--docker"]) == 0
    assert seen["command"][1:] == ["-m", "sentinel"]   # no --fake
    out = capsys.readouterr().out
    assert "killed at 16.0s by claude" in out
    assert out.strip().endswith("docker compose up -d --force-recreate")


def test_demo_docker_mode_prints_reset_even_on_failure(monkeypatch, capsys):
    def boom(store, child, timeout):
        raise RuntimeError("no beta metrics")

    monkeypatch.setattr(demo.subprocess, "Popen", lambda command, **kw: FakeChild())
    monkeypatch.setattr(demo, "timeline", boom)
    monkeypatch.setitem(sys.modules, "shared.store", SimpleNamespace(get_store=lambda: None))
    assert demo.main(["--docker"]) == 1
    assert "force-recreate" in capsys.readouterr().out
