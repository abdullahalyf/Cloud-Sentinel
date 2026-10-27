"""The sentinel writes an alert with rule 'sentinel_heartbeat' every HEARTBEAT_SECONDS, via SafeStore."""
from dataclasses import replace

from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.sources import FakeSource
from shared.config import load_settings
from shared.store import LocalStore
from tests.test_db_outage import FlakyStore, ReadOnlyStore

cfg = replace(load_settings(), anthropic_api_key="", gemini_api_key="", webhook_url="")


def beats(store):
    return [a for a in store.recent_alerts(limit=500) if a["rule"] == "sentinel_heartbeat"]


def make(store, run_cfg=cfg):
    return Sentinel(FakeSource(run_cfg, auto_rogue=None), store, Brain(run_cfg), run_cfg)


def test_heartbeat_is_written_at_the_first_tick_and_then_every_five_seconds(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    s = make(store)
    assert cfg.heartbeat_seconds == 5.0
    for now in (1000.0, 1001.0, 1004.9, 1005.0, 1009.0, 1010.0):
        s.tick(now=now)
    rows = beats(store)
    assert len(rows) == 3                                    # 1000, 1005, 1010
    assert rows[0]["agent"] == "sentinel" and rows[0]["severity"] == "info"
    assert "alive" in rows[0]["message"]


def test_heartbeat_comes_from_the_real_loop_clock(tmp_path):
    import time

    store = LocalStore(str(tmp_path / "t.db"))
    s = make(store, replace(cfg, heartbeat_seconds=0.5, tick_seconds=0.1))
    end = time.time() + 1.6
    while time.time() < end:
        s.tick()
        time.sleep(0.1)
    assert len(beats(store)) >= 3


def test_database_down_never_blocks_the_loop_or_floods_the_buffer(tmp_path):
    store = FlakyStore(str(tmp_path / "t.db"))
    store.down = True
    s = make(store, replace(cfg, store_retry_seconds=5.0))
    for i in range(30):                         # 30 ticks, 1s apart, database dead the whole time
        s.tick(now=1000.0 + i)                  # must never raise
    heartbeats = [row for method, (row, *_) in s.store.buffer if method == "insert_alert"
                  and row.rule == "sentinel_heartbeat"]
    assert len(heartbeats) <= 2                 # not one per 5s: queued only when a retry is due
    store.down = False
    s.store.down_until = 0.0
    s.tick(now=1100.0)
    assert beats(store)                         # and heartbeats resume once the database is back


def test_read_only_database_keeps_the_loop_running(tmp_path):
    store = ReadOnlyStore(str(tmp_path / "t.db"))
    s = make(store)
    for i in range(10):
        s.tick(now=1000.0 + i * 5)
    assert not beats(store)                     # nothing could be written, nothing raised
    queued = [row for method, (row, *_) in s.store.buffer if method == "insert_alert"]
    assert 1 <= len(queued) <= 3                # one per retry that was due, not one per tick


def test_heartbeat_goes_through_safestore(tmp_path):
    s = make(LocalStore(str(tmp_path / "t.db")))
    from sentinel.safe_store import SafeStore

    assert isinstance(s.store, SafeStore)
