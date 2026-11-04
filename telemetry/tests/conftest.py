"""Fixtures for SDK / adapter tests: real OTel spans in memory → real OTLP encoder → our collector normalizer,
and the SDK's HTTP calls routed to an in-process API (mock or real brain) instead of the network."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))
import cloudsentinel as cs  # noqa: E402


@pytest.fixture
def captured():
    """Returns get_rows(): every span the SDK finished so far, normalized exactly like the collector does."""
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from telemetry.collector.normalize import normalize_otlp_protobuf

    mem = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test-agent",
                                                        "cloudsentinel.agent.id": "test-agent"}))
    provider.add_span_processor(SimpleSpanProcessor(mem))
    old = (cs._s.agent_id, cs._s.tracer, cs._s.provider)
    cs._s.agent_id, cs._s.tracer, cs._s.provider = "test-agent", provider.get_tracer("t"), provider

    def get_rows():
        spans = mem.get_finished_spans()
        return normalize_otlp_protobuf(encode_spans(spans).SerializeToString()) if spans else []

    yield get_rows
    cs._s.agent_id, cs._s.tracer, cs._s.provider = old


def route_sdk_to(monkeypatch, app):
    """Make cs._api() talk to a FastAPI app in-process."""
    client = TestClient(app)

    def fake_api(method, path, body=None, timeout=5.0):
        r = client.request(method, path, json=body)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None
    monkeypatch.setattr(cs, "_api", fake_api)
    return client


@pytest.fixture
def mock_api(monkeypatch):
    from shared.mocks import mock_api as m

    m.seed()
    yield route_sdk_to(monkeypatch, m.app)
    m.seed()


@pytest.fixture
def no_api(monkeypatch):
    """The C2 API is unreachable."""
    import urllib.error

    def down(*a, **kw):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(cs, "_api", down)
