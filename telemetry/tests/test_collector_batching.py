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
