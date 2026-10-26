"""Database outage: the guard keeps detecting and killing; writes are buffered and retried."""
import time
from dataclasses import replace

from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.safe_store import SafeStore
from sentinel.sources import FakeSource
from shared.config import load_settings
from shared.contracts import AlertRow, CommandRow
from shared.store import LocalStore

cfg = replace(load_settings(), anthropic_api_key="", store_retry_seconds=0.0)


class FlakyStore(LocalStore):
    """A LocalStore whose every call fails while `down` is True."""

    def __init__(self, path):
        super().__init__(path)
        self.down = False

    def __getattribute__(self, name):
        if name in ("insert_metric", "insert_alert", "insert_action", "pending_commands",
                    "finish_command") and object.__getattribute__(self, "down"):
            raise ConnectionError("database unreachable")
        return object.__getattribute__(self, name)


def test_db_down_and_rogue_agent_still_killed(tmp_path):
    store = FlakyStore(str(tmp_path / "t.db"))
    store.down = True
    source = FakeSource(cfg, auto_rogue=None)
    s = Sentinel(source, store, Brain(cfg), cfg)
    beta = source.agents["beta"]
    beta.rogue_since = beta.next_call = time.time() - 15
    end = time.time() + 3
    while time.time() < end and beta.alive:
        s.tick()   # must never raise
        for f in list(s.pending.values()):
            f.result(timeout=5)
        time.sleep(0.2)
    assert not beta.alive
    assert source.agents["alpha"].alive and source.agents["gamma"].alive
    assert s.store.buffer   # rows waited in memory

    store.down = False      # database is back → the buffered KILL lands
    s.tick()
    assert not s.store.buffer
    assert [a["agent"] for a in store.recent_actions() if a["action"] == "KILL"] == ["beta"]


def test_buffer_retries_in_order_and_waits_between_tries(tmp_path):
    now = [100.0]
    store = FlakyStore(str(tmp_path / "t.db"))
    safe = SafeStore(store, replace(cfg, store_retry_seconds=5.0), clock=lambda: now[0])
    store.down = True
    safe.insert_alert(AlertRow("a", "info", "r", "first"))
    safe.insert_alert(AlertRow("a", "info", "r", "second"))
    assert len(safe.buffer) == 2 and safe.is_down
    assert safe.pending_commands() == []
    store.down = False
    safe.insert_alert(AlertRow("a", "info", "r", "third"))   # still inside the retry wait → buffered
    assert len(safe.buffer) == 3
    now[0] += 6
    assert safe.flush() and not safe.buffer
    assert [a["message"] for a in reversed(store.recent_alerts())] == ["first", "second", "third"]


def test_full_buffer_drops_oldest(tmp_path):
    store = FlakyStore(str(tmp_path / "t.db"))
    store.down = True
    safe = SafeStore(store, replace(cfg, store_buffer_size=2))
    for i in range(3):
        safe.insert_alert(AlertRow("a", "info", "r", str(i)))
    assert [args[0].message for _, args in safe.buffer] == ["1", "2"] and safe.dropped == 1


def test_commands_resume_after_outage(tmp_path):
    store = FlakyStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None)
    s = Sentinel(source, store, Brain(cfg), cfg)
    store.insert_command(CommandRow("gamma", "KILL", "test"))
    store.down = True
    s.tick()
    assert source.agents["gamma"].alive   # can't read commands while down
    store.down = False
    s.tick()
    assert not source.agents["gamma"].alive


class PoisonStore(LocalStore):
    """Database is fine, but one alert (message 'poison') is always rejected."""

    def insert_alert(self, row):
        if row.message == "poison":
            raise ValueError("value too long for column")
        super().insert_alert(row)


def test_poison_row_is_dropped_after_five_tries_and_kill_switch_keeps_working(tmp_path):
    store = PoisonStore(str(tmp_path / "t.db"))
    safe = SafeStore(store, replace(cfg, store_retry_seconds=0.0, store_max_row_failures=5))
    safe.insert_alert(AlertRow("a", "info", "r", "poison"))   # fails → buffered (looks like an outage so far)
    safe.insert_alert(AlertRow("a", "info", "r", "fine-1"))
    assert safe.pending_commands() == []   # no command yet, but no error either
    store.insert_command(CommandRow("beta", "KILL", "dashboard", "kill switch"))
    for _ in range(6):
        cmds = safe.pending_commands()      # the Kill switch must not get stuck behind the poison row
    assert [c["command"] for c in cmds] == ["KILL"]
    assert not safe.buffer and safe.poisoned == 1
    assert [a["message"] for a in store.recent_alerts()] == ["fine-1"]


def test_rows_survive_a_long_outage_they_are_not_poison(tmp_path):
    store = FlakyStore(str(tmp_path / "t.db"))
    safe = SafeStore(store, replace(cfg, store_retry_seconds=0.0, store_max_row_failures=5))
    store.down = True
    for i in range(4):
        safe.insert_alert(AlertRow("a", "info", "r", f"m{i}"))
    for _ in range(50):        # many failed retries while the whole database is down
        safe.flush()
    assert len(safe.buffer) == 4 and safe.poisoned == 0
    store.down = False
    assert safe.flush() and not safe.buffer
    assert [a["message"] for a in store.recent_alerts()][::-1] == ["m0", "m1", "m2", "m3"]
