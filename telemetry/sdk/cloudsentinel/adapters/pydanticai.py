"""
Pydantic AI adapter.   Owner: Fojle.

Pydantic AI already emits OpenTelemetry GenAI spans (invoke_agent, chat, execute_tool). This adapter only
adds what CloudSentinel needs on top of them, plus the tool gate:

    import cloudsentinel as cs
    from cloudsentinel.adapters.pydanticai import instrument, guard

    cs.init(agent_id="pai-refund")
    instrument()

    @agent.tool_plain
    @guard(value_usd=lambda a: a["amount"] / 122, fail_closed=True)
    def issue_refund(order_id: int, amount: int) -> str: ...

guard() uses cs.gate() (no span of its own) and writes the decision on Pydantic AI's own execute_tool span,
so there is one span per tool call.
"""
from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable, Optional, Union

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import SpanProcessor

import cloudsentinel as cs

log = logging.getLogger("cloudsentinel.pydantic_ai")

ValueFn = Union[float, Callable[[dict], float], None]
KNOWN_OPS = ("invoke_agent", "chat", "execute_tool")
# LIMITATION: Pydantic AI sets gen_ai.input.messages only when a chat span ENDS, and an ended span cannot be
# changed. So chat spans have no prompt_preview / prompt_hash, and prompt-based loop detection (exact and
# semantic repeats) does not work for Pydantic AI agents. Token counts, tools, budgets and the gate do.


class CloudSentinelSpanProcessor(SpanProcessor):
    """Adds CloudSentinel attributes to Pydantic AI's spans when they start. Errors are logged, never raised."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        try:
            self._start(span)
        except Exception:  # telemetry must never break the agent
            log.exception("cloudsentinel pydantic-ai processor failed")

    def _start(self, span: Any) -> None:
        attrs = dict(span.attributes or {})
        op = attrs.get(cs.OPERATION)
        if op not in KNOWN_OPS:     # our own spans set their operation after they start: skipped here
            return
        span.set_attribute(cs.CS_AGENT_ID, cs._s.agent_id)
        if op == "execute_tool" and attrs.get("gen_ai.tool.call.arguments") is not None:
            span.set_attribute(cs.CS_TOOL_ARGS, str(attrs["gen_ai.tool.call.arguments"])[:500])

    def on_end(self, span: Any) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def instrument() -> CloudSentinelSpanProcessor:
    """Call after cs.init(). Pydantic AI's spans go through the CloudSentinel tracer provider."""
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings

    provider = cs._s.provider
    if provider is None:
        raise RuntimeError("cs.init() first (and install opentelemetry-sdk)")
    processor = CloudSentinelSpanProcessor()
    provider.add_span_processor(processor)
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider))
    return processor


def guard(fn: Optional[Callable] = None, value_usd: ValueFn = None, fail_closed: bool = False) -> Callable:
    """Decorator for a plain (sync) function. Put it UNDER @agent.tool_plain. Every call waits if the agent is
    paused, asks the tool gate, and raises cs.ToolDenied on deny / timeout. rewrite runs with the new args."""
    def deco(f: Callable) -> Callable:
        if inspect.iscoroutinefunction(f):
            raise TypeError("guard() supports plain (sync) functions")
        name = f.__name__
        sig = inspect.signature(f)

        @functools.wraps(f)
        def run(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            call = dict(bound.arguments)
            value = value_usd(call) if callable(value_usd) else value_usd
            cs.wait_if_paused()
            decision, final = cs.gate(name, call, value, fail_closed)
            try:   # the current span is Pydantic AI's execute_tool span
                span = otel_trace.get_current_span()
                span.set_attribute(cs.CS_TOOL_DECISION, decision)
                if value is not None:
                    span.set_attribute(cs.CS_TOOL_VALUE_USD, float(value))
                if decision in ("deny", "timeout"):
                    span.set_attribute(cs.ERROR_TYPE, f"tool_{decision}")
            except Exception:
                log.exception("could not write the gate decision on the span")
            if decision in ("deny", "timeout"):
                raise cs.ToolDenied(f"{name} was {decision}")
            return f(**(final if decision == "rewrite" else call))

        return run

    return deco(fn) if callable(fn) else deco


__all__ = ["CloudSentinelSpanProcessor", "instrument", "guard"]