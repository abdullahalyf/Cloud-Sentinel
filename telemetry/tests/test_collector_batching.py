import queue

from fastapi.testclient import TestClient

from shared.store import LocalStore
from telemetry.collector.app import create_app
from telemetry.collector.batcher import SpanBatcher, flush
from telemetry.tests.test_normalize import make_span, payload


class CountingStore:
    def __init__(self):
        self.calls = []

    def insert_spans(self, rows):
        self.calls.append(len(rows))


def test_three_requests_become_one_insert_call():
    store = CountingStore()
    client = TestClient(create_app(store, batcher=SpanBatcher(store, wait=0.5)))
    for _ in range(3):
        assert client.post("/v1/traces", json=payload([make_span()])).status_code == 200
    flush()
    assert store.calls == [3]


def test_flush_empties_the_queue_and_the_rows_are_stored():
    store = LocalStore(":memory:")
    batcher = SpanBatcher(store, wait=0.05)
    client = TestClient(create_app(store, batcher=batcher))
    client.post("/v1/traces", json=payload([make_span(), make_span()]))
    flush()
    assert batcher.qsize() == 0
    assert len(store.spans_after(0)) == 2


def test_a_big_request_is_split_into_batches_of_at_most_500():
    store = CountingStore()
    client = TestClient(create_app(store, batcher=SpanBatcher(store, wait=0.05)))
    assert client.post("/v1/traces", json=payload([make_span() for _ in range(1200)])).status_code == 200
    flush()
    assert sum(store.calls) == 1200 and max(store.calls) <= 500


def test_a_full_queue_answers_503_with_retry_after():
    store = CountingStore()
    client = TestClient(create_app(store, batcher=SpanBatcher(store, max_rows=2, wait=0.05)))
    r = client.post("/v1/traces", json=payload([make_span() for _ in range(5)]))
    assert r.status_code == 503 and r.headers["retry-after"] == "1"


def test_default_queue_size_is_10000():
    from telemetry.collector.batcher import MAX_QUEUE_ROWS

    assert MAX_QUEUE_ROWS == 10000
    assert SpanBatcher(CountingStore())._q.maxsize == 10000


def test_flush_returns_true_only_when_everything_is_written():
    store = CountingStore()
    batcher = SpanBatcher(store, wait=0.05)
    client = TestClient(create_app(store, batcher=batcher))
    assert client.post("/v1/traces", json=payload([make_span(), make_span()])).status_code == 200
    assert batcher.flush(timeout=2) is True
    assert batcher.qsize() == 0 and sum(store.calls) == 2


class FlakyStore:
    """insert_spans() raises for the first `fail_times` calls, then works."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0
        self.stored = []

    def insert_spans(self, rows):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("supabase is slow")
        self.stored.append(len(rows))


def _client(store, **kw):
    batcher = SpanBatcher(store, wait=0.05, **kw)
    return batcher, TestClient(create_app(store, batcher=batcher))


def test_a_store_that_fails_twice_then_works_loses_nothing():
    store = FlakyStore(fail_times=2)
    batcher, client = _client(store, retry_delays=(0, 0, 0, 0, 0))
    assert client.post("/v1/traces", json=payload([make_span(), make_span()])).status_code == 200
    assert batcher.flush(timeout=3) is True
    assert store.calls == 3 and store.stored == [2]
    assert batcher.failed_batches == 0


def test_a_store_that_never_works_drops_the_batch_after_6_tries_and_the_thread_lives():
    store = FlakyStore(fail_times=999)
    batcher, client = _client(store, retry_delays=(0, 0, 0, 0, 0))
    client.post("/v1/traces", json=payload([make_span()]))
    assert batcher.flush(timeout=3) is True
    assert store.calls == 6 and store.stored == []
    assert batcher.failed_batches == 1
    store.fail_times = 0                      # the store comes back
    client.post("/v1/traces", json=payload([make_span()]))
    assert batcher.flush(timeout=3) is True
    assert store.stored == [1]                # the same thread still works


def test_the_backoff_is_0_2_0_4_0_8_1_6_3_2_seconds():
    from telemetry.collector.batcher import RETRY_DELAYS

    assert RETRY_DELAYS == (0.2, 0.4, 0.8, 1.6, 3.2)
    store = FlakyStore(fail_times=999)
    slept = []
    batcher, client = _client(store)
    batcher._sleep = slept.append
    client.post("/v1/traces", json=payload([make_span()]))
    assert batcher.flush(timeout=3) is True
    assert slept == [0.2, 0.4, 0.8, 1.6, 3.2]


def test_healthz_reports_the_counters():
    store = CountingStore()
    batcher, client = _client(store)
    client.post("/v1/traces", json=payload([make_span(), make_span()]))
    assert batcher.flush(timeout=3) is True
    h = client.get("/healthz").json()
    assert h == {"queue": 0, "accepted": 2, "dropped": 0, "failed_batches": 0, "store": "ok"}


def test_healthz_counts_dropped_requests_and_shows_a_broken_store():
    store = FlakyStore(fail_times=999)
    batcher, client = _client(store, retry_delays=(0,), max_rows=3)
    client.post("/v1/traces", json=payload([make_span()]))
    assert batcher.flush(timeout=3) is True
    assert client.post("/v1/traces", json=payload([make_span() for _ in range(5)])).status_code == 503
    h = client.get("/healthz").json()
    assert h["dropped"] == 1 and h["failed_batches"] == 1 and h["store"] == "error"


def test_a_body_over_4mb_is_rejected_with_413_and_counted():
    store = CountingStore()
    batcher, client = _client(store)
    big = b"x" * (4 * 1024 * 1024 + 1)
    r = client.post("/v1/traces", content=big, headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 413
    assert client.get("/healthz").json()["dropped"] == 1
    assert store.calls == []


def test_a_body_just_under_4mb_is_not_rejected_for_size():
    store = CountingStore()
    batcher, client = _client(store)
    ok = b"\xff" * (4 * 1024 * 1024)
    r = client.post("/v1/traces", content=ok, headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 400          # garbage, but not "too big"


def test_chunked_body_over_4mb_is_rejected_even_without_content_length():
    store = CountingStore()
    batcher, client = _client(store)

    def chunks():
        for _ in range(5):
            yield b"x" * (1024 * 1024)

    r = client.post("/v1/traces", content=chunks(), headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 413
    assert client.get("/healthz").json()["dropped"] == 1
    assert store.calls == []


def test_healthz_goes_back_to_ok_after_the_store_recovers():
    store = FlakyStore(fail_times=1)
    batcher, client = _client(store, retry_delays=())
    client.post("/v1/traces", json=payload([make_span()]))
    assert batcher.flush(timeout=3) is True
    assert client.get("/healthz").json()["store"] == "error"
    client.post("/v1/traces", json=payload([make_span()]))
    assert batcher.flush(timeout=3) is True
    h = client.get("/healthz").json()
    assert h["store"] == "ok" and h["failed_batches"] == 1
