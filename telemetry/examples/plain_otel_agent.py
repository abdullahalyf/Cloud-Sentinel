"""
A plain OpenTelemetry agent: NO CloudSentinel SDK, only opentelemetry-sdk and the OTLP exporter.
It sends 20 chat spans (GenAI semantic conventions) with service.name = "external" to the collector.
It proves that any OTel-instrumented agent shows up in CloudSentinel.

    python telemetry/examples/plain_otel_agent.py            # collector on http://127.0.0.1:4318
    OTEL_EXPORTER_OTLP_ENDPOINT=http://host:4318 python telemetry/examples/plain_otel_agent.py
"""
import os
import time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SPANS = 20
PROMPTS = ["Where is my parcel?", "Can I return a shirt?", "Do you deliver to Sylhet?", "Is my bKash payment received?"]  # synthetic


def build_provider(exporter=None) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": "external"}))
    if exporter is None:
        base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318").rstrip("/")
        exporter = OTLPSpanExporter(endpoint=base + "/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def run(provider: TracerProvider, spans: int = SPANS, pause: float = 0.0) -> None:
    tracer = provider.get_tracer("plain-otel-agent")
    for i in range(spans):
        with tracer.start_as_current_span("chat claude-haiku-5-5") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.provider.name", "anthropic")
            span.set_attribute("gen_ai.request.model", "claude-haiku-5-5")
            span.set_attribute("gen_ai.usage.input_tokens", 120 + i)
            span.set_attribute("gen_ai.usage.output_tokens", 40 + i)
        time.sleep(pause)
    provider.force_flush()


if __name__ == "__main__":
    prov = build_provider()
    trace.set_tracer_provider(prov)
    run(prov, pause=0.2)
    prov.shutdown()
    print(f"sent {SPANS} chat spans as service.name=external")