"""
The brain's verdict, on the agent's own trace (A15).

**The problem this solves.** The agent's behaviour lives on an OpenTelemetry trace —
in Phoenix, in Grafana, in whatever the customer already looks at. The brain's
decision about that behaviour lived in CloudSentinel's own tables: an alert row, a
verdict row, an action row. So the cause and the effect were on two different
screens, and the person asking *"why did CloudSentinel pause this agent?"* had to
look at both and join them by hand.

A15 puts the verdict on the trace, as a span event on a span that belongs to the
agent. Phoenix then shows it next to the behaviour that caused it.

**How it reaches Phoenix without touching anybody else's folder.** Phoenix is fed
by the collector (`telemetry/collector/app.py`), and the collector forwards the
**raw OTLP body** it received — `phoenix.submit(body, ctype)` — not the rows it
normalized out of it. So a span event inside that body survives the whole way to
Phoenix without a single line changing in `telemetry/` or `shared/store.py`, which
belong to Fojle.

The brain therefore emits a real OTel span, over OTLP/HTTP, to the collector:

  * it carries the **agent's own `trace_id`**, so it lands on the agent's trace;
  * it carries the **`semantic_loop` event**, which is what the verdict *is*;
  * it carries the **numbers** — the loop score, the repeat count, the confidence —
    because a verdict without its evidence is an opinion.

**It can never break the brain.** Telemetry is the one part of the system that is
allowed to fail. The OTel packages may be missing, the collector may be down,
Phoenix may be slow. None of that may stop a tick: the emit returns a bool and
swallows every exception. A lost verdict is a nuisance; a lost tick is an outage.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from shared.contracts import Attr

log = logging.getLogger("brain.verdict_span")

# The event name — what the verdict is called inside the trace.
EVENT_NAME = "semantic_loop"
# The operation — what kind of span this is, for the collector and for a reader.
OPERATION = "cs_verdict"
# A reason is a sentence, not a document. An unbounded reason would bloat every trace
# it landed on, and Phoenix keeps the event forever.
MAX_REASON = 300
# The span name. OTel GenAI names its spans "<operation> <subject>".
SPAN_NAME = f"{OPERATION} {{agent_id}}"


def build(agent_id: str, trace_id: str, parent_span_id: str, action: str, source: str,
          confidence: float, reason: str, loop_score: float, exact_repeats: int) -> dict:
    """The verdict, as the plain data the emitter needs. No I/O, so it is testable.

    `trace_id` and `parent_span_id` come from the agent's own span, so the verdict
    lands on the agent's trace. An agent that is not instrumented has none, and the
    verdict is emitted without a parent — visible, but not attached to anything.
    """
    return {
        "agent_id": agent_id,
        "operation": OPERATION,
        "name": SPAN_NAME.format(agent_id=agent_id),
        "trace_id": (trace_id or "").strip().lower(),
        "parent_span_id": (parent_span_id or "").strip().lower(),
        "event": {
            "name": EVENT_NAME,
            "attributes": {
                Attr.CS_LOOP_SCORE: round(float(loop_score or 0.0), 4),
                Attr.CS_EXACT_REPEATS: int(exact_repeats or 0),
                Attr.CS_VERDICT_CONFIDENCE: round(float(confidence or 0.0), 4),
                Attr.CS_VERDICT_ACTION: str(action or ""),
                Attr.CS_VERDICT_SOURCE: str(source or ""),
                Attr.CS_VERDICT_REASON: str(reason or "")[:MAX_REASON],
            },
        },
        "attributes": {
            Attr.CS_AGENT_ID: agent_id,
            Attr.OPERATION: OPERATION,
            Attr.AGENT_ID: agent_id,
            Attr.CS_LOOP_SCORE: round(float(loop_score or 0.0), 4),
            Attr.CS_EXACT_REPEATS: int(exact_repeats or 0),
            Attr.CS_VERDICT_CONFIDENCE: round(float(confidence or 0.0), 4),
            Attr.CS_VERDICT_ACTION: str(action or ""),
            Attr.CS_VERDICT_SOURCE: str(source or ""),
            Attr.CS_VERDICT_REASON: str(reason or "")[:MAX_REASON],
        },
    }


# ── the emitter ─────────────────────────────────────────────────────────────
class Emitter:
    """Sends the verdict to the collector over OTLP/HTTP.

    The OTel SDK is a dependency of the repo, but the brain must not *require* it:
    a deployment without the packages still has to make decisions, and a missing
    package must not take the tick with it. So the provider is built lazily and
    every failure is swallowed.
    """

    def __init__(self, endpoint: str = "", project: str = "cloudsentinel"):
        self.endpoint = (endpoint or "").rstrip("/")
        self.project = project
        self._tracer: Any = None
        self._provider: Any = None
        self._built = False
        self.sent = 0
        self.failed = 0

    def enabled(self) -> bool:
        return bool(self.endpoint)

    def _get_tracer(self) -> Any:
        """Build the tracer once. `None` means "no OTel here" — not an error."""
        if self._built:
            return self._tracer
        self._built = True
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider = TracerProvider(resource=Resource.create({
                "service.name": "cloudsentinel-brain",
                Attr.CS_RUNTIME: "brain",
            }))
            exporter = OTLPSpanExporter(endpoint=f"{self.endpoint}/v1/traces")
            # The default schedule delay is 5 s. A verdict is something an operator is
            # watching for *now*, so it goes out within a second. The batch still batches
            # — a burst of verdicts is one request, not one request each.
            provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=1000))
            self._tracer = provider.get_tracer("cloudsentinel.brain")
            self._provider = provider
        except Exception as exc:
            log.info("the verdict spans are off: %s", exc)
            self._tracer = None
        return self._tracer

    def submit(self, verdict: dict) -> bool:
        """Emit one verdict. Never raises."""
        if not self.enabled():
            return False
        try:
            tracer = self._get_tracer()
            if tracer is None:
                return False
            _emit_span(tracer, verdict)
            self.sent += 1
            return True
        except Exception as exc:
            self.failed += 1
            log.warning("could not send the verdict span: %s", exc)
            return False


def _emit_span(tracer: Any, verdict: dict) -> None:
    """The span itself, on the agent's trace, with the verdict as an event."""
    from opentelemetry import trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    attributes = verdict.get("attributes") or {}
    context = None
    trace_id = str(verdict.get("trace_id") or "")
    parent_span_id = str(verdict.get("parent_span_id") or "")
    if trace_id and parent_span_id:
        # The agent's own trace: the verdict is a child of the span that was judged.
        parent = SpanContext(trace_id=int(trace_id, 16),
                             span_id=int(parent_span_id, 16),
                             is_remote=True,
                             trace_flags=TraceFlags(TraceFlags.SAMPLED))
        context = trace.set_span_in_context(NonRecordingSpan(parent))

    span = tracer.start_span(str(verdict.get("name") or OPERATION), context=context, attributes=attributes)
    event = verdict.get("event") or {}
    span.add_event(str(event.get("name") or EVENT_NAME), event.get("attributes") or {})
    span.end()


# The module-level emitter, so the engine does not build one per verdict.
_emitter: Optional[Emitter] = None


def configure(endpoint: str = "", project: str = "cloudsentinel") -> None:
    """Point the emitter at the collector. An empty endpoint turns it off."""
    global _emitter
    _emitter = Emitter(endpoint=endpoint, project=project)


def emitter() -> Emitter:
    """The emitter, created on first use and off until it is configured."""
    global _emitter
    if _emitter is None:
        _emitter = Emitter()
    return _emitter


def emit(sender: Any, agent_id: str, trace_id: str, parent_span_id: str, action: str, source: str,
         confidence: float, reason: str, loop_score: float, exact_repeats: int) -> bool:
    """Emit one verdict through `sender` (anything with a `submit(verdict)`).

    The sender is a parameter so the test can pass one that raises — the point of the
    test is that a broken sender cannot break the brain.
    """
    verdict = build(agent_id=agent_id, trace_id=trace_id, parent_span_id=parent_span_id, action=action,
                    source=source, confidence=confidence, reason=reason, loop_score=loop_score,
                    exact_repeats=exact_repeats)
    try:
        return bool(sender.submit(verdict))
    except Exception as exc:
        log.warning("could not send the verdict span: %s", exc)
        return False


# ── finding the agent's trace ────────────────────────────────────────────────
def trace_of(spans: list[dict]) -> tuple[str, str]:
    """The (trace_id, span_id) of the most recent span that has a trace.

    The verdict is attached to the agent's trace, so it has to be attached to
    *something* in it. The most recent span with a trace id is the one that was
    judged, so the verdict hangs off it. Spans without a trace id are skipped —
    an agent that emits them is not instrumented.
    """
    for span in reversed(list(spans or [])):
        trace_id = str((span or {}).get("trace_id") or "").strip()
        span_id = str((span or {}).get("span_id") or "").strip()
        if trace_id and span_id:
            return trace_id, span_id
    return "", ""
