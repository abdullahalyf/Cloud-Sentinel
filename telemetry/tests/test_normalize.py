from fastapi.testclient import TestClient

from shared.store import LocalStore
from telemetry.collector.app import create_app
from telemetry.collector.normalize import normalize_otlp_json


def make_span(name="chat claude-haiku-5-5", attrs=None, status_code=0):
    """Helper: one OTLP-JSON span. attrs = {"key": value} (str / int / float)."""
    def val(v):
        return {"intValue": str(v)} if isinstance(v, int) else {"doubleValue": v} if isinstance(v, float) else {"stringValue": v}
    return {"traceId": "0af7651916cd43dd8448eb211c80319c", "spanId": "b7ad6b7169203331", "name": name,
            "startTimeUnixNano": "1730000000000000000", "endTimeUnixNano": "1730000000500000000",
            "attributes": [{"key": k, "value": val(v)} for k, v in (attrs or {}).items()],
            "status": {"code": status_code}}


def payload(spans, resource=None):
    res = [{"key": k, "value": {"stringValue": v}} for k, v in (resource or {"service.name": "beta"}).items()]
    return {"resourceSpans": [{"resource": {"attributes": res}, "scopeSpans": [{"spans": spans}]}]}


def test_chat_span_is_normalized_and_priced():
    rows = normalize_otlp_json(payload([make_span(attrs={
        "gen_ai.operation.name": "chat", "gen_ai.request.model": "claude-haiku-5-5",
        "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 200,
        "cloudsentinel.prompt.preview": "Fetch order 4471"})]))
    r = rows[0]
    assert (r.agent_id, r.operation, r.model, r.input_tokens, r.output_tokens) == ("beta", "chat", "claude-haiku-5-5", 1000, 200)
    assert r.cost_usd > 0 and r.prompt_hash and r.duration_ms == 500.0 and r.trace_id.startswith("0af7")


def test_collector_accepts_protobuf_from_the_real_otel_sdk():
    """The standard OTLP exporter sends protobuf. Encode spans with the real SDK encoder and post them."""
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    mem = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "external"}))
    provider.add_span_processor(SimpleSpanProcessor(mem))
    with provider.get_tracer("t").start_as_current_span("execute_tool orders_api") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", "orders_api")
    body = encode_spans(mem.get_finished_spans()).SerializeToString()
    store = LocalStore(":memory:")
    r = TestClient(create_app(store)).post("/v1/traces", content=body, headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 200
    row = store.spans_after(0)[0]
    assert row["agent_id"] == "external" and row["tool_name"] == "orders_api" and len(row["span_id"]) == 16


def test_collector_rejects_garbage():
    r = TestClient(create_app(LocalStore(":memory:"))).post("/v1/traces", content=b"\xff\x00garbage",
                                                            headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 400
