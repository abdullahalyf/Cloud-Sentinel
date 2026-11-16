import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from telemetry.collector.normalize import normalize_otlp_protobuf  # noqa: E402

TEL = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


real = _load("real_agent", TEL / "simulators" / "real_agent.py")
plain = _load("plain_otel_agent", TEL / "examples" / "plain_otel_agent.py")


class FakeClient:
    def __init__(self):
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="It ships tomorrow.")],
                               usage=SimpleNamespace(input_tokens=321, output_tokens=17))


def test_real_agent_records_usage_and_sends_no_temperature(captured):
    client = FakeClient()
    assert real.answer(client, "Do you deliver to Sylhet?") == "It ships tomorrow."
    assert "temperature" not in client.kwargs and client.kwargs["model"] == real.MODEL
    chat = [r for r in captured() if r.operation == "chat"]
    assert len(chat) == 1
    assert (chat[0].input_tokens, chat[0].output_tokens) == (321, 17)
    assert chat[0].model == real.MODEL and chat[0].provider == "anthropic" and chat[0].cost_usd > 0


def test_plain_otel_agent_sends_20_chat_spans_as_external_without_the_sdk():
    mem = InMemorySpanExporter()
    provider = plain.build_provider(exporter=mem)
    provider._active_span_processor._span_processors = ()          # keep only the in-memory exporter
    provider.add_span_processor(SimpleSpanProcessor(mem))
    plain.run(provider)
    spans = mem.get_finished_spans()
    assert len(spans) == 20
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    rows = normalize_otlp_protobuf(encode_spans(spans).SerializeToString())
    assert len(rows) == 20 and all(r.agent_id == "external" and r.operation == "chat" for r in rows)
    assert all(r.input_tokens > 0 and r.cost_usd > 0 for r in rows)


def test_plain_otel_agent_does_not_import_the_cloudsentinel_sdk():
    src = (TEL / "examples" / "plain_otel_agent.py").read_text(encoding="utf-8")
    assert "cloudsentinel" not in src.replace("CloudSentinel", "")