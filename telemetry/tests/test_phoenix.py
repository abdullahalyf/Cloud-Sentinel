"""Optional Phoenix export: off by default, forwards enriched protobuf in the background, never breaks the collector."""
from dataclasses import replace

from fastapi.testclient import TestClient

import cloudsentinel as cs
from shared.config import settings
from shared.store import LocalStore
from telemetry.collector.app import create_app
from telemetry.collector.phoenix import PhoenixExporter, from_settings, to_phoenix_body


def _otlp_body(captured_rows_fn=None):
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    mem = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "lg-refund"}))
    provider.add_span_processor(SimpleSpanProcessor(mem))
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("chat sim") as s:
        s.set_attribute("gen_ai.operation.name", "chat")
        s.set_attribute("gen_ai.request.model", "sim")
        s.set_attribute("gen_ai.usage.input_tokens", 300)
        s.set_attribute("gen_ai.usage.output_tokens", 50)
        s.set_attribute("cloudsentinel.prompt.preview", "Fetch order 4471")
    with tracer.start_as_current_span("graph_node retry") as s:
        s.set_attribute("gen_ai.operation.name", "graph_node")
        s.set_attribute("cloudsentinel.node.state_delta", '{"answer": "retrying"}')
    return encode_spans(mem.get_finished_spans()).SerializeToString()


def _decode(data: bytes) -> dict:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    return MessageToDict(ExportTraceServiceRequest.FromString(data))


def test_off_by_default():
    assert from_settings(settings) is None
    assert from_settings(replace(settings, export_phoenix=True, phoenix_endpoint="http://x:6006")).url == \
        "http://x:6006/v1/traces"


def test_enrichment_adds_openinference_and_keeps_originals():
    out = _decode(to_phoenix_body(_otlp_body(), "application/x-protobuf", "cloudsentinel"))
    rs = out["resourceSpans"][0]
    res = {a["key"]: a["value"] for a in rs["resource"]["attributes"]}
    assert res["openinference.project.name"]["stringValue"] == "cloudsentinel"
    spans = {s["name"]: {a["key"]: a["value"] for a in s["attributes"]} for s in rs["scopeSpans"][0]["spans"]}
    chat, node = spans["chat sim"], spans["graph_node retry"]
    assert chat["openinference.span.kind"]["stringValue"] == "LLM" and chat["llm.token_count.total"]["intValue"] == "350"
    assert chat["gen_ai.usage.input_tokens"]["intValue"] == "300"        # original kept
    assert chat["input.value"]["stringValue"] == "Fetch order 4471"
    assert node["openinference.span.kind"]["stringValue"] == "CHAIN" and "retrying" in node["output.value"]["stringValue"]


def test_collector_forwards_in_background_and_survives_phoenix_down():
    sent, store = [], LocalStore(":memory:")
    good = PhoenixExporter("http://phoenix:6006", post=lambda url, data, headers: sent.append((url, headers, data)))
    r = TestClient(create_app(store, good)).post("/v1/traces", content=_otlp_body(),
                                                 headers={"content-type": "application/x-protobuf"})
    good.join()
    assert r.status_code == 200 and len(store.spans_after(0)) == 2            # CloudSentinel got the spans
    assert sent and sent[0][0] == "http://phoenix:6006/v1/traces" and sent[0][1]["Content-Type"] == "application/x-protobuf"

    def down(url, data, headers):
        raise ConnectionError("phoenix is down")
    bad = PhoenixExporter("http://phoenix:6006", api_key="k", post=down)
    r = TestClient(create_app(LocalStore(":memory:"), bad)).post("/v1/traces", content=_otlp_body(),
                                                                 headers={"content-type": "application/x-protobuf"})
    bad.join()
    assert r.status_code == 200 and bad.failed == 1 and bad.headers["Authorization"] == "Bearer k"


def test_json_payloads_are_converted_to_protobuf():
    from telemetry.tests.test_normalize import make_span, payload

    data = to_phoenix_body(__import__("json").dumps(payload([make_span(attrs={"gen_ai.operation.name": "chat"})])).encode(),
                           "application/json", "p")
    assert _decode(data)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] == "chat claude-haiku-5-5"
