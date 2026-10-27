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


class ReadOnlyStore(LocalStore):
    """Reads work, every write fails after `delay` seconds (a slow Supabase in read-only mode)."""

    def __init__(self, path, delay=0.0):
        super().__init__(path)
        self.read_only, self.delay, self.write_calls = True, delay, 0

    def __getattribute__(self, name):
        if name in ("insert_metric", "insert_alert", "insert_action", "finish_command") \
                and object.__getattribute__(self, "read_only"):
            def fail(*args, **kwargs):
                self.write_calls += 1
                time.sleep(self.delay)
                raise PermissionError("cannot execute INSERT in a read-only transaction")
            return fail
        return object.__getattribute__(self, name)


def test_read_only_database_is_retried_rarely_and_backs_off(tmp_path):
    now = [100.0]
    store = ReadOnlyStore(str(tmp_path / "t.db"))
    safe = SafeStore(store, replace(cfg, store_retry_seconds=5.0), clock=lambda: now[0])
    for i in range(300):                     # a long read-only stretch: lots of rows are waiting
        safe.insert_alert(AlertRow("a", "info", "r", str(i)))
    assert len(safe.buffer) == 300 and store.write_calls == 1   # only the very first write was even tried
    waits, last_calls = [], store.write_calls
    for _ in range(100):                     # a tick every 0.5s for 50s
        now[0] += 0.5
        safe.insert_alert(AlertRow("a", "info", "r", f"t{now[0]}"))
        safe.pending_commands()
        if store.write_calls != last_calls:
            waits.append(now[0])
            assert store.write_calls - last_calls <= 3, "a retry may make only a few failing calls"
            last_calls = store.write_calls
    gaps = [b - a for a, b in zip(waits, waits[1:])]
    assert waits and all(g >= 5.0 for g in gaps), gaps       # never more than once per 5s
    assert gaps == sorted(gaps) and gaps[-1] > gaps[0]       # and the wait grows while it keeps failing
    assert safe.poisoned == 0 and len(safe.buffer) == 400    # a read-only database loses nothing
    store.read_only = False
    now[0] += 60
    assert safe.flush() and not safe.buffer
    landed = [a["message"] for a in store.recent_alerts(limit=1000)][::-1]
    assert len(landed) == 400 and landed[:3] == ["0", "1", "2"]           # all rows landed, in order


def test_kill_switch_works_while_the_database_is_read_only(tmp_path):
    store = ReadOnlyStore(str(tmp_path / "t.db"))
    store.insert_command(CommandRow("beta", "KILL", "dashboard", "kill switch"))
    safe = SafeStore(store, replace(cfg, store_retry_seconds=5.0))
    safe.insert_alert(AlertRow("a", "info", "r", "x"))
    assert [c["command"] for c in safe.pending_commands()] == ["KILL"]   # reads are not blocked by failing writes


def test_ticks_stay_fast_and_rogue_dies_in_about_5s_in_read_only_mode(tmp_path):
    store = ReadOnlyStore(str(tmp_path / "t.db"), delay=0.25)   # every failing write costs 0.25s
    run_cfg = replace(cfg, store_retry_seconds=5.0)
    source = FakeSource(run_cfg, auto_rogue=None)
    s = Sentinel(source, store, Brain(run_cfg), run_cfg)
    beta = source.agents["beta"]
    beta.rogue_since = beta.next_call = started = time.time()
    worst = 0.0
    while beta.alive and time.time() - started < 12:
        t = time.time()
        s.tick()
        for f in list(s.pending.values()):
            f.result(timeout=5)
        worst = max(worst, time.time() - t)
        time.sleep(0.2)
    assert not beta.alive and time.time() - started <= 8, "rogue must still die in ~5s"
    assert worst < 1.0, f"a tick took {worst:.2f}s"
