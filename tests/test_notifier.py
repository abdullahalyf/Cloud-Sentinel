"""Webhook notifier with a mocked urlopen. No network."""
import json
import threading
import time

from sentinel.engine import Sentinel
from sentinel.notifier import Notifier
from sentinel.sources import FakeSource
from shared.config import load_settings
from shared.contracts import CommandRow
from shared.store import LocalStore
from tests.test_engine import FixedBrain

cfg = load_settings()
hooked = cfg.__class__(**{**cfg.__dict__, "webhook_url": "https://hooks.example/abc", "anthropic_api_key": ""})


class Recorder:
    def __init__(self, delay=0.0, error=None):
        self.delay, self.error, self.requests = delay, error, []

    def __call__(self, req, timeout=None):
        time.sleep(self.delay)
        if self.error:
            raise self.error
        self.requests.append((req, timeout))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"ok"


def test_posts_discord_and_slack_compatible_json(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("urllib.request.urlopen", rec)
    Notifier(hooked).notify("beta", "KILL", "claude", "stuck in a loop").result(timeout=5)
    req, timeout = rec.requests[0]
    body = json.loads(req.data)
    assert req.full_url == "https://hooks.example/abc" and req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    assert body["content"] == body["text"] and "KILL beta" in body["text"] and "stuck" in body["text"]
    assert timeout == hooked.webhook_timeout_seconds


def test_no_url_means_no_post(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("urllib.request.urlopen", rec)
    off = cfg.__class__(**{**cfg.__dict__, "webhook_url": ""})
    assert Notifier(off).notify("beta", "KILL", "rules", "x") is None
    assert rec.requests == []


def test_failure_only_logs(monkeypatch, caplog):
    monkeypatch.setattr("urllib.request.urlopen", Recorder(error=OSError("connection refused")))
    Notifier(hooked).notify("beta", "KILL", "rules", "x").result(timeout=5)   # no exception
    assert "webhook failed" in caplog.text


def test_slow_webhook_does_not_block_kill_or_pause(monkeypatch, tmp_path):
    rec = Recorder(delay=2.0)
    monkeypatch.setattr("urllib.request.urlopen", rec)
    store = LocalStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None)
    s = Sentinel(source, store, FixedBrain(None), hooked)
    h = {x.name: x for x in source.list_agents()}
    started = time.time()
    assert s.kill(h["beta"], actor="human", reason="test")
    store.insert_command(CommandRow("alpha", "PAUSE", reason="look closer"))
    s.tick()
    assert time.time() - started < 1.0
    s.notifier.pool.shutdown(wait=True)
    texts = [json.loads(r.data)["text"] for r, _ in rec.requests]
    assert any("KILL beta" in t for t in texts) and any("PAUSE alpha" in t for t in texts)
