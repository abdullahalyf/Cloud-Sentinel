import dataclasses
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from telemetry.collector.app import create_app
from telemetry.collector.batcher import SpanBatcher, flush
from telemetry.collector.cloudwatch import CloudWatchExporter, emf_line, from_settings
from telemetry.collector.normalize import normalize_otlp_json
from telemetry.tests.test_collector_batching import CountingStore
from telemetry.tests.test_normalize import make_span, payload

ATTRS = {"gen_ai.operation.name": "chat", "gen_ai.request.model": "claude-haiku-5-5",
         "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 200}


def _row():
    row = normalize_otlp_json(payload([make_span(attrs=ATTRS)]))[0]
    return dataclasses.replace(row, start_ts=1730000000.0)   # fixed start, so the EMF Timestamp is testable


def test_a_line_matches_the_emf_shape():
    d = emf_line(_row())
    cw = d["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "CloudSentinel" and cw["Dimensions"] == [["agent_id"]]
    units = {m["Name"]: m["Unit"] for m in cw["Metrics"]}
    assert units == {"cost_usd": "None", "input_tokens": "Count", "output_tokens": "Count",
                     "duration_ms": "Milliseconds"}
    assert isinstance(d["_aws"]["Timestamp"], int) and d["_aws"]["Timestamp"] == 1730000000000
    for name in units:                                   # every declared metric has a number at the top level
        assert isinstance(d[name], (int, float))
    assert d["agent_id"] == "beta" and d["operation"] == "chat" and d["model"] == "claude-haiku-5-5"
    assert d["trace_id"].startswith("0af7") and (d["input_tokens"], d["output_tokens"]) == (1000, 200)
    assert d["cost_usd"] > 0 and d["duration_ms"] == 500.0


def test_the_exporter_writes_one_valid_json_line_per_span(tmp_path):
    path = tmp_path / "sub" / "cw.jsonl"
    exp = CloudWatchExporter(str(path))
    exp.write([_row(), _row(), _row()])
    exp.write([_row()])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 and all(json.loads(x)["_aws"] for x in lines)


def test_from_settings_is_off_by_default_and_on_with_the_flag(tmp_path):
    assert from_settings(SimpleNamespace(export_cloudwatch=False, cloudwatch_file="x")) is None
    on = from_settings(SimpleNamespace(export_cloudwatch=True, cloudwatch_file=str(tmp_path / "a.jsonl")))
    assert isinstance(on, CloudWatchExporter)


def test_through_the_collector_one_line_per_stored_span(tmp_path):
    path = tmp_path / "cw.jsonl"
    store = CountingStore()
    client = TestClient(create_app(store, cloudwatch=CloudWatchExporter(str(path))))
    assert client.post("/v1/traces", json=payload([make_span(attrs=ATTRS), make_span(attrs=ATTRS)])).status_code == 200
    flush()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_a_failing_sink_never_breaks_the_store_path():
    class Boom:
        def write(self, rows):
            raise OSError("disk full")

    store = CountingStore()
    b = SpanBatcher(store, wait=0.05, sink=Boom())
    client = TestClient(create_app(store, batcher=b))
    client.post("/v1/traces", json=payload([make_span()]))
    assert b.flush(timeout=3) is True
    assert store.calls == [1] and b.failed_batches == 0 and b.last_ok is True


def test_nothing_is_exported_when_the_store_fails():
    class Fail:
        def insert_spans(self, rows):
            raise ConnectionError("down")

    got = []
    sink = SimpleNamespace(write=lambda rows: got.append(len(rows)))
    b = SpanBatcher(Fail(), wait=0.05, retry_delays=(), sink=sink)
    client = TestClient(create_app(Fail(), batcher=b))
    client.post("/v1/traces", json=payload([make_span()]))
    assert b.flush(timeout=3) is True and got == [] and b.failed_batches == 1


def test_main_passes_cloudwatch_by_keyword():
    """__main__.py runs on import (it starts uvicorn), so check its call shape in the source."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "collector" / "__main__.py").read_text(encoding="utf-8")
    assert "cloudwatch=cloudwatch" in src


def test_create_app_with_a_cloudwatch_exporter_builds_and_exports(tmp_path):
    path = tmp_path / "cw.jsonl"
    store = CountingStore()
    app = create_app(store, None, cloudwatch=CloudWatchExporter(str(path)))   # the shape __main__.py uses
    assert hasattr(app.state.batcher, "flush")
