"""
The brain's verdict, on the agent's own trace (A15) — the brain side.

The agent's behaviour lives on an OpenTelemetry trace; the brain's decision about it
lived only in CloudSentinel's own tables. A15 puts the verdict on the trace, so the
person looking at the agent in Phoenix sees *why* it was stopped next to *what it did*.

What is pinned here:

  1. **The verdict lands on the agent's trace** — the same `trace_id`, so it is the
     same trace and not a lonely span of its own.
  2. **It is an event with the numbers** — the score, the repeats, the confidence.
  3. **It cannot break the brain** — the emitter swallows every failure, and the tick
     goes on.
  4. **The collector forwards it** — the collector forwards the *raw OTLP body* to
     Phoenix, so the event survives the trip. This is the part that would silently
     break if the collector ever changed to forward the rows instead of the body.
"""
from __future__ import annotations

import json

import pytest

from brain import verdict_span
from shared.contracts import Attr


class FakeSender:
    """Collects the verdicts instead of sending them."""

    def __init__(self):
        self.verdicts: list[dict] = []

    def submit(self, verdict: dict) -> bool:
        self.verdicts.append(verdict)
        return True


# ── it lands on the agent's trace ───────────────────────────────────────────
def test_the_verdict_is_on_the_agents_own_trace():
    sender = FakeSender()
    verdict_span.emit(sender, agent_id="beta", trace_id="11223344556677889900aabbccddeeff",
                      parent_span_id="1111111111111111", action="PAUSE", source="fallback",
                      confidence=0.85, reason="semantic loop", loop_score=0.85, exact_repeats=4)
    assert len(sender.verdicts) == 1
    assert sender.verdicts[0]["trace_id"] == "11223344556677889900aabbccddeeff"
    assert sender.verdicts[0]["parent_span_id"] == "1111111111111111"


def test_an_uninstrumented_agent_still_gets_a_verdict():
    """Not every agent is instrumented. The verdict is still emitted — it just has
    no trace to hang off, because there is no trace."""
    sender = FakeSender()
    verdict_span.emit(sender, agent_id="beta", trace_id="", parent_span_id="", action="PAUSE",
                      source="fallback", confidence=0.85, reason="r", loop_score=0.85, exact_repeats=4)
    assert sender.verdicts[0]["trace_id"] == ""


def test_the_trace_is_found_from_the_agents_spans():
    """The verdict has to be attached to *something* in the agent's trace. The most
    recent span that has a trace is the one that was judged."""
    spans = [
        {"trace_id": "aa", "span_id": "11"},
        {"trace_id": "bb", "span_id": "22"},
    ]
    assert verdict_span.trace_of(spans) == ("bb", "22")


def test_a_span_without_a_trace_is_skipped():
    """An agent can emit spans that carry no trace id. Those cannot be a parent."""
    spans = [
        {"trace_id": "aa", "span_id": "11"},
        {"trace_id": "", "span_id": "22"},
    ]
    assert verdict_span.trace_of(spans) == ("aa", "11")


def test_an_agent_with_no_spans_has_no_trace():
    assert verdict_span.trace_of([]) == ("", "")
    assert verdict_span.trace_of([{"trace_id": "", "span_id": ""}]) == ("", "")


# ── it is an event with the numbers ─────────────────────────────────────────
def test_the_verdict_is_an_event_on_the_span():
    sender = FakeSender()
    verdict_span.emit(sender, agent_id="beta", trace_id="aa", parent_span_id="bb", action="PAUSE",
                      source="fallback", confidence=0.85, reason="because", loop_score=0.85,
                      exact_repeats=7)
    event = sender.verdicts[0]["event"]
    assert event["name"] == "semantic_loop"
    assert event["attributes"][Attr.CS_LOOP_SCORE] == 0.85
    assert event["attributes"][Attr.CS_EXACT_REPEATS] == 7
    assert event["attributes"][Attr.CS_VERDICT_ACTION] == "PAUSE"
    assert event["attributes"][Attr.CS_VERDICT_SOURCE] == "fallback"
    assert event["attributes"][Attr.CS_VERDICT_CONFIDENCE] == 0.85


def test_the_verdict_carries_the_numbers_on_the_span_too():
    """A reader that only looks at the span's attributes — not its events — still
    sees the verdict. Events are the richer form; attributes are the plain one."""
    sender = FakeSender()
    verdict_span.emit(sender, agent_id="beta", trace_id="aa", parent_span_id="bb", action="KILL",
                      source="claude", confidence=0.9, reason="r", loop_score=0.9, exact_repeats=9)
    attrs = sender.verdicts[0]["attributes"]
    assert attrs[Attr.CS_LOOP_SCORE] == 0.9
    assert attrs[Attr.CS_VERDICT_ACTION] == "KILL"
    assert attrs[Attr.CS_VERDICT_SOURCE] == "claude"


def test_the_agent_is_named_on_the_span():
    sender = FakeSender()
    verdict_span.emit(sender, agent_id="beta", trace_id="aa", parent_span_id="bb", action="PAUSE",
                      source="fallback", confidence=0.5, reason="r", loop_score=0.5, exact_repeats=1)
    assert sender.verdicts[0]["attributes"][Attr.CS_AGENT_ID] == "beta"


def test_the_verdict_is_its_own_operation():
    """`cs_verdict` — the brain talking about the agent, not the agent doing
    something. If it were ever confused with `chat` or `execute_tool`, the brain
    would read its own verdict back as behaviour and start judging its judgement."""
    verdict = verdict_span.build(agent_id="beta", trace_id="aa", parent_span_id="bb", action="PAUSE",
                                 source="fallback", confidence=0.5, reason="r", loop_score=0.5,
                                 exact_repeats=1)
    assert verdict["operation"] == "cs_verdict"
    assert verdict["name"] == "cs_verdict beta"


def test_the_reason_is_truncated():
    """A reason is a sentence, not a document. An unbounded reason would bloat every
    trace it lands on, and Phoenix keeps the event forever."""
    verdict = verdict_span.build(agent_id="beta", trace_id="aa", parent_span_id="bb", action="PAUSE",
                                 source="fallback", confidence=0.5, reason="x" * 5000, loop_score=0.5,
                                 exact_repeats=1)
    assert len(verdict["attributes"][Attr.CS_VERDICT_REASON]) <= 300
    assert len(verdict["event"]["attributes"][Attr.CS_VERDICT_REASON]) <= 300


def test_the_trace_ids_are_lowercased():
    """OTLP trace ids are hex. The collector lowercases them, so the brain does too —
    otherwise the same trace would be spelled two ways."""
    verdict = verdict_span.build(agent_id="beta", trace_id="AABBCCDDEEFF00112233445566778899",
                                 parent_span_id="1111111111111111", action="PAUSE", source="fallback",
                                 confidence=0.5, reason="r", loop_score=0.5, exact_repeats=1)
    assert verdict["trace_id"] == "aabbccddeeff00112233445566778899"


# ── it cannot break the brain ───────────────────────────────────────────────
def test_a_broken_sender_does_not_raise():
    class Broken:
        def submit(self, *a, **k):
            raise RuntimeError("the collector is down")

    assert verdict_span.emit(Broken(), agent_id="beta", trace_id="aa", parent_span_id="bb",
                             action="PAUSE", source="fallback", confidence=0.5, reason="r",
                             loop_score=0.5, exact_repeats=1) is False


def test_a_missing_sender_does_not_raise():
    assert verdict_span.emit(None, agent_id="beta", trace_id="aa", parent_span_id="bb",
                             action="PAUSE", source="fallback", confidence=0.5, reason="r",
                             loop_score=0.5, exact_repeats=1) is False


def test_the_emitter_is_off_without_an_endpoint():
    """No endpoint, no spans. The brain must not try to send them."""
    e = verdict_span.Emitter(endpoint="")
    assert e.enabled() is False
    assert e.submit({"attributes": {}, "name": "x"}) is False


def test_the_emitter_survives_a_broken_otel():
    """The OTel packages may be missing. That is not an error — the brain still
    makes its decisions, it just cannot show them on the trace."""
    e = verdict_span.Emitter(endpoint="http://localhost:4318")
    e._built = True
    e._tracer = None
    assert e.submit({"attributes": {}, "name": "x", "event": {}}) is False
    assert e.failed == 0   # "no OTel" is not a failure, it is just off


# ── the engine puts it there ────────────────────────────────────────────────
def test_the_engine_emits_the_verdict(sim, cfg, monkeypatch):
    """A verdict the judge reached is put on the agent's trace."""
    sender = FakeSender()
    sim.engine.verdict_emitter = sender
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.run(30)
    assert sender.verdicts, "the engine should have emitted a verdict span"
    v = sender.verdicts[0]
    assert v["agent_id"] == "beta"
    assert v["event"]["name"] == "semantic_loop"


def test_the_engine_never_dies_when_the_emitter_breaks(sim, cfg):
    """A collector that is down must not stop the tick."""
    class Broken:
        def submit(self, *a, **k):
            raise RuntimeError("the collector is down")

    sim.engine.verdict_emitter = Broken()
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.run(30)          # no exception
    assert sim.state("beta") in ("paused", "probation", "suspicious", "killed", "healthy")


def test_the_verdict_reaches_the_trace_of_the_agent(sim, cfg):
    """The whole point: the verdict's trace id is the agent's, not a new one."""
    sender = FakeSender()
    sim.engine.verdict_emitter = sender
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.run(30)
    # The sim runs on a virtual clock (t=1000), so `recent_spans` — which filters on
    # wall-clock time — would find nothing. `spans_after` reads them all.
    agent_traces = {s.get("trace_id") for s in sim.store.spans_after(0)
                    if s.get("agent_id") == "beta"}
    agent_traces.discard("")
    agent_traces.discard(None)
    emitted = {v["trace_id"] for v in sender.verdicts} - {""}
    assert emitted, "the verdict should carry a trace id"
    assert emitted <= agent_traces, f"the verdict's trace {emitted} is not the agent's {agent_traces}"


# ── the collector forwards it ───────────────────────────────────────────────
def test_the_collector_forwards_the_raw_body_so_the_event_survives():
    """The whole reason A15 needs no change in telemetry/: the collector forwards the
    **raw OTLP body** to Phoenix, not the rows it normalized out of it.

    If the collector ever changed to forward the rows instead, the span event would be
    silently dropped on the way to Phoenix — and this test would say so.
    """
    import inspect

    from telemetry.collector.app import create_app

    src = inspect.getsource(create_app)
    assert "phoenix.submit(body, ctype)" in src, \
        "the collector must forward the raw body — the rows lose the span events"


def test_the_collector_stores_the_verdict_span_as_a_span():
    """The verdict arrives at the collector as a span, and is stored like one."""
    from telemetry.collector.normalize import normalize_span

    attributes = {
        Attr.OPERATION: "cs_verdict",
        Attr.CS_AGENT_ID: "beta",
        Attr.CS_LOOP_SCORE: 0.85,
        Attr.CS_VERDICT_ACTION: "PAUSE",
    }
    span = {
        "name": "cs_verdict beta",
        "traceId": "11223344556677889900aabbccddeeff",
        "spanId": "1111111111111111",
        "parentSpanId": "2222222222222222",
        "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attributes.items()],
    }
    row = normalize_span(span, {})
    assert row.operation == "cs_verdict"
    assert row.agent_id == "beta"
    assert row.trace_id == "11223344556677889900aabbccddeeff"
    assert row.parent_span_id == "2222222222222222"


def test_the_brain_does_not_ingest_its_own_verdict_as_behaviour():
    """The verdict is a span about the agent, so the collector stores it. If the brain
    then read it back as behaviour, the brain would be judging its own judgement —
    and the loop score would climb because of the verdicts, not the agent.

    The window only counts `chat` and `execute_tool` spans, so a verdict span is
    ignored. This test pins that.
    """
    from brain.state import AgentWindow

    win = AgentWindow("beta")
    win.add({"operation": "cs_verdict", "name": "cs_verdict beta", "start_ts": 1000.0,
             "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
             "prompt_preview": "semantic loop score 0.85", "prompt_hash": "h1"})
    assert len(win.chats) == 0
    assert len(win.tools) == 0
    assert win.snapshot(1000.0, budget_usd=1.0).exact_repeats == 0


# ── the whole way to the collector ──────────────────────────────────────────
def test_the_verdict_reaches_the_collector_with_the_agents_trace():
    """The real thing, end to end: the brain emits over OTLP, a real HTTP server
    receives the protobuf, and the collector's own normalizer reads it back.

    This is the test that says the verdict is *on the agent's trace* and not merely
    somewhere in the vicinity — the trace id and the parent come back unchanged.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from telemetry.collector.normalize import normalize_otlp_protobuf

    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — the stdlib spells it this way
            received.append(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        verdict = verdict_span.build("beta", "11223344556677889900aabbccddeeff", "1111111111111111",
                                     "PAUSE", "fallback", 0.85, "semantic loop", 0.85, 4)
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(
            OTLPSpanExporter(endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces")))
        verdict_span._emit_span(provider.get_tracer("test"), verdict)
        for _ in range(100):
            if received:
                break
            import time as _time
            _time.sleep(0.05)
    finally:
        server.shutdown()

    assert received, "the collector never received the span"
    rows = normalize_otlp_protobuf(received[0])
    assert len(rows) == 1
    row = rows[0]
    assert row.operation == "cs_verdict"
    assert row.agent_id == "beta"
    assert row.trace_id == "11223344556677889900aabbccddeeff"
    assert row.parent_span_id == "1111111111111111"


def test_the_span_event_survives_in_the_raw_body():
    """The event is what the verdict *is*, and it is only in the raw body — the
    rows the collector normalizes out of it have no event. So the collector must
    forward the body, and the event goes with it.

    This is the check that would fail first if A15 were reimplemented in a way that
    only put the numbers on the span's attributes.
    """
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        verdict = verdict_span.build("beta", "11223344556677889900aabbccddeeff", "1111111111111111",
                                     "PAUSE", "fallback", 0.85, "semantic loop", 0.85, 4)
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(
            OTLPSpanExporter(endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces")))
        verdict_span._emit_span(provider.get_tracer("test"), verdict)
        for _ in range(100):
            if received:
                break
            import time as _time
            _time.sleep(0.05)
    finally:
        server.shutdown()

    assert received
    request = ExportTraceServiceRequest()
    request.ParseFromString(received[0])
    span = MessageToDict(request)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert [e["name"] for e in span.get("events", [])] == ["semantic_loop"]
    keys = {a["key"] for a in span["events"][0]["attributes"]}
    assert Attr.CS_LOOP_SCORE in keys and Attr.CS_VERDICT_ACTION in keys


def test_the_verdict_lands_in_the_collectors_store():
    """The whole journey: the brain emits, the real collector app receives it over
    OTLP/HTTP, and the row lands in the store — with the agent's trace on it.

    This is the test that would fail if the collector or the exporter ever stopped
    agreeing on the trace id.
    """
    import socket
    import threading
    import time as _time

    import uvicorn

    from shared.store import LocalStore
    from telemetry.collector.app import create_app

    store = LocalStore(":memory:")
    app = create_app(store, phoenix=None)

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    _time.sleep(1.5)
    try:
        emitter = verdict_span.Emitter(endpoint=f"http://127.0.0.1:{port}")
        verdict = verdict_span.build("beta", "11223344556677889900aabbccddeeff", "1111111111111111",
                                     "PAUSE", "fallback", 0.85, "semantic loop", 0.85, 4)
        assert emitter.submit(verdict) is True
        for _ in range(100):
            if store.spans_after(0):
                break
            _time.sleep(0.1)
    finally:
        server.should_exit = True

    rows = store.spans_after(0)
    assert len(rows) == 1, f"the collector stored {len(rows)} spans"
    row = rows[0]
    assert row["operation"] == "cs_verdict"
    assert row["agent_id"] == "beta"
    assert row["trace_id"] == "11223344556677889900aabbccddeeff"
    assert row["parent_span_id"] == "1111111111111111"
