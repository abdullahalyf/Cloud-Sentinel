import pytest

from shared.store import SupabaseStore


class FakeChannel:
    def __init__(self, fail=False):
        self.fail, self.listen = fail, []

    def on_postgres_changes(self, event, callback, table=None, schema=None, filter=None, select=None):
        self.listen.append({"event": event, "callback": callback, "table": table, "schema": schema})
        return self

    async def subscribe(self, callback=None):
        if self.fail:
            raise RuntimeError("join refused")
        return self


class FakeRealtime:
    def __init__(self, fail=False):
        self.channel_obj, self.topics, self.closed = FakeChannel(fail), [], False

    def channel(self, topic, params=None):
        self.topics.append(topic)
        return self.channel_obj

    async def close(self):
        self.closed = True


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr("supabase.create_client", lambda url, key: object())
    return SupabaseStore("https://x.supabase.co", "k")


def _payload(record):
    return {"data": {"record": record, "type": "INSERT", "table": "alerts"}, "ids": [1]}


def test_watch_listens_to_inserts_of_the_table_and_decodes_the_row(store):
    rt, got = FakeRealtime(), []
    stop = store.watch("tool_calls", got.append, client_factory=lambda: rt)
    listen = rt.channel_obj.listen[0]
    assert listen["table"] == "tool_calls" and listen["schema"] == "public" and listen["event"] == "INSERT"
    assert rt.topics == ["cs-watch-tool_calls"]
    listen["callback"](_payload({"id": 7, "args": '{"amount": 50000}'}))
    assert got == [{"id": 7, "args": {"amount": 50000}}]      # JSON text column decoded like the other reads
    stop()
    assert rt.closed is True


def test_a_change_without_a_record_is_ignored(store):
    rt, got = FakeRealtime(), []
    stop = store.watch("alerts", got.append, client_factory=lambda: rt)
    rt.channel_obj.listen[0]["callback"](_payload(None))
    stop()
    assert got == []


def test_a_callback_that_raises_does_not_break_the_watch(store):
    rt, got = FakeRealtime(), []

    def boom(row):
        got.append(row)
        raise ValueError("bad callback")

    stop = store.watch("alerts", boom, client_factory=lambda: rt)
    handler = rt.channel_obj.listen[0]["callback"]
    handler(_payload({"id": 1}))
    handler(_payload({"id": 2}))
    stop()
    assert [r["id"] for r in got] == [1, 2]


def test_a_failed_subscription_raises(store):
    with pytest.raises(RuntimeError):
        store.watch("alerts", lambda row: None, client_factory=lambda: FakeRealtime(fail=True))


def test_the_default_client_uses_the_realtime_url_and_the_key(store, monkeypatch):
    made = {}

    class Real(FakeRealtime):
        def __init__(self, url, token=None):
            super().__init__()
            made["url"], made["token"] = url, token

    monkeypatch.setattr("realtime.AsyncRealtimeClient", Real)
    stop = store.watch("alerts", lambda row: None)
    stop()
    assert made == {"url": "wss://x.supabase.co/realtime/v1", "token": "k"}