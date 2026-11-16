"""
OpenAI Agents SDK adapter: one tracing processor, no change to your agents.   Owner: Fojle.

    import cloudsentinel as cs
    from cloudsentinel.adapters.openai_agents import instrument, guard

    cs.init(agent_id="oai-refund")
    instrument()

    @function_tool
    @guard(value_usd=lambda a: a["amount"] / 122, fail_closed=True)
    def issue_refund(order_id: int, amount: int) -> str: ...

What you get (CONTRACTS section 4):
  trace          -> invoke_agent span (task success / failure)
  agent run      -> graph_node {agent} span (framework "openai-agents")
  handoff        -> graph_node {from_agent} span with next = the target agent
  model call     -> chat {model} span with token usage
  tool call      -> execute_tool {tool} span; tools wrapped with guard() also go through the tool gate
"""
from __future__ import annotations

import functools
import inspect
import logging
import threading
import uuid
from typing import Any, Callable, Optional, Union

from agents.tracing import TracingProcessor
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace

import cloudsentinel as cs

log = logging.getLogger("cloudsentinel.openai_agents")

ValueFn = Union[float, Callable[[dict], float], None]
FRAMEWORK = "openai-agents"
_GUARDED: set[str] = set()   # tool names wrapped by guard(): guard() already emits their execute_tool span


def _usage(data: Any) -> tuple[int, int]:
    """(input, output) tokens of a generation / response span. Key names differ between APIs."""
    tin = tout = 0
    try:
        u = getattr(data, "usage", None) or {}
        tin = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
        tout = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
        if not (tin or tout):
            ru = getattr(getattr(data, "response", None), "usage", None)
            tin, tout = int(getattr(ru, "input_tokens", 0) or 0), int(getattr(ru, "output_tokens", 0) or 0)
    except (AttributeError, TypeError, ValueError):
        pass
    return tin, tout


def _prompt_of(data: Any) -> str:
    """Best effort: the last message of the model input (needed for loop detection)."""
    inp = getattr(data, "input", None)
    if isinstance(inp, str):
        return inp
    if isinstance(inp, (list, tuple)) and inp:
        last = inp[-1]
        content = last.get("content") if isinstance(last, dict) else getattr(last, "content", None)
        if isinstance(content, str):
            return content
    return ""


def _clean(attrs: dict) -> dict:
    return {k: v for k, v in attrs.items() if v is not None}


class CloudSentinelProcessor(TracingProcessor):
    """openai-agents TracingProcessor -> CloudSentinel spans. Errors are logged, never raised."""

    def __init__(self) -> None:
        self._spans: dict[str, Any] = {}               # sdk span_id -> open OTel span
        self._parent: dict[str, Optional[str]] = {}    # sdk span_id -> parent span_id (also for ignored spans)
        self._trace_span: dict[str, Any] = {}          # trace_id -> invoke_agent span
        self._failed: set[str] = set()                 # trace_ids with a failed span
        self._step = 0
        self._ctx: dict[str, Any] = {}                 # sdk span_id -> OTel context token (guarded tools)
        self._lock = threading.Lock()

    def _safe(self, fn: Callable, *args: Any) -> None:
        try:
            fn(*args)
        except Exception:  # telemetry must never break the agent
            log.exception("cloudsentinel openai-agents processor failed")

    def _parent_span(self, span: Any) -> Any:
        pid = span.parent_id
        while pid is not None:
            if pid in self._spans:
                return self._spans[pid]
            pid = self._parent.get(pid)
        return self._trace_span.get(span.trace_id)

    # ── trace = one task ──
    def on_trace_start(self, trace: Any) -> None:
        self._safe(self._trace_start, trace)

    def _trace_start(self, trace: Any) -> None:
        span = cs.start_span(f"invoke_agent {cs._s.agent_id}", "invoke_agent", {
            cs.AGENT_NAME: cs._s.agent_id, cs.AGENT_ID: cs._s.agent_id,
            cs.CS_TASK_ID: uuid.uuid4().hex[:12], cs.CS_TASK_STATUS: "abandoned"})
        with self._lock:
            self._trace_span[trace.trace_id] = span

    def on_trace_end(self, trace: Any) -> None:
        self._safe(self._trace_end, trace)

    def _trace_end(self, trace: Any) -> None:
        with self._lock:
            span = self._trace_span.pop(trace.trace_id, None)
            failed = trace.trace_id in self._failed
            self._failed.discard(trace.trace_id)
        if span is not None:
            span.set_attribute(cs.CS_TASK_STATUS, "failure" if failed else "success")
            cs.end_span(span, "span_error" if failed else None)

    # ── spans ──
    def on_span_start(self, span: Any) -> None:
        self._safe(self._span_start, span)

    def _span_start(self, span: Any) -> None:
        data = span.span_data
        kind = data.type
        with self._lock:
            self._parent[span.span_id] = span.parent_id
            parent = self._parent_span(span)
            if kind == "agent":
                self._step += 1
                name, op, attrs = f"graph_node {data.name}", "graph_node", {
                    cs.CS_NODE: data.name, cs.CS_NODE_STEP: self._step, cs.CS_NODE_FRAMEWORK: FRAMEWORK}
            elif kind == "handoff":
                node = getattr(data, "from_agent", None) or "handoff"
                name, op, attrs = f"graph_node {node}", "graph_node", {
                    cs.CS_NODE: node, cs.CS_NODE_FRAMEWORK: FRAMEWORK}
            elif kind in ("generation", "response"):
                model = getattr(data, "model", None) or getattr(getattr(data, "response", None), "model", None) or "unknown"
                name, op, attrs = f"chat {model}", "chat", {cs.PROVIDER: "openai", cs.REQUEST_MODEL: str(model)}
            elif kind == "function" and data.name not in _GUARDED:
                name, op, attrs = f"execute_tool {data.name}", "execute_tool", {
                    cs.TOOL_NAME: data.name, cs.TOOL_CALL_ID: span.span_id[-12:], cs.CS_TOOL_DECISION: "allow"}
            elif kind == "function":   # guarded tool: guard() emits the span; make the node span current so it nests
                if parent is not None:
                    self._ctx[span.span_id] = otel_context.attach(otel_trace.set_span_in_context(parent))
                return
            else:
                return   # turn / task / custom: no span of ours
            self._spans[span.span_id] = cs.start_span(name, op, _clean(attrs), parent=parent)

    def on_span_end(self, span: Any) -> None:
        self._safe(self._span_end, span)

    def _span_end(self, span: Any) -> None:
        with self._lock:
            otel = self._spans.pop(span.span_id, None)
            token = self._ctx.pop(span.span_id, None)
            self._parent.pop(span.span_id, None)
            if span.error:
                self._failed.add(span.trace_id)
        if token is not None:
            try:
                otel_context.detach(token)
            except Exception:  # ended in another context: harmless for telemetry
                pass
        if otel is None:
            return
        data = span.span_data
        kind = data.type
        if kind in ("generation", "response"):
            tin, tout = _usage(data)
            otel.set_attribute(cs.INPUT_TOKENS, tin)
            otel.set_attribute(cs.OUTPUT_TOKENS, tout)
            model = getattr(data, "model", None) or getattr(getattr(data, "response", None), "model", None)
            if model:
                otel.set_attribute(cs.REQUEST_MODEL, str(model))
                otel.update_name(f"chat {model}")
            prompt = _prompt_of(data)
            if prompt:
                otel.set_attribute(cs.CS_PROMPT_HASH, cs._prompt_hash(prompt))
                if cs._s.capture_prompts:
                    otel.set_attribute(cs.CS_PROMPT_PREVIEW, prompt[:200])
        elif kind == "function":
            otel.set_attribute(cs.CS_TOOL_ARGS, str(data.input if data.input is not None else "{}")[:500])
        elif kind == "handoff":
            if getattr(data, "to_agent", None):
                otel.set_attribute(cs.CS_NODE_NEXT, str(data.to_agent))
        err = span.error
        cs.end_span(otel, str((err or {}).get("message", "error"))[:100] if err else None)

    def shutdown(self) -> None:
        self._safe(self._shutdown)

    def _shutdown(self) -> None:
        with self._lock:
            open_spans = list(self._spans.values()) + list(self._trace_span.values())
            self._spans.clear()
            self._trace_span.clear()
        for span in open_spans:
            cs.end_span(span)
        cs.flush()

    def force_flush(self) -> None:
        self._safe(cs.flush)


def instrument() -> CloudSentinelProcessor:
    """Add the CloudSentinel processor next to the SDK's default one."""
    import agents

    processor = CloudSentinelProcessor()
    agents.add_trace_processor(processor)
    return processor


def guard(fn: Optional[Callable] = None, value_usd: ValueFn = None, fail_closed: bool = False) -> Callable:
    """Decorator for a plain (sync) Python function: every call goes through the CloudSentinel tool gate
    (allow / deny / rewrite / approval). Put it UNDER @function_tool, with plain parameters:

        @function_tool
        @guard(value_usd=lambda a: a["amount"] / 122, fail_closed=True)
        def issue_refund(order_id: int, amount: int) -> str: ...

    value_usd: money at risk (number, or a function of the args). Use fail_closed=True for money-moving
    tools. A denied call raises cs.ToolDenied; a paused agent waits first (cs.wait_if_paused)."""
    def deco(f: Callable) -> Callable:
        if inspect.iscoroutinefunction(f):
            raise TypeError("guard() supports plain (sync) functions")
        name = f.__name__
        _GUARDED.add(name)
        sig = inspect.signature(f)

        @functools.wraps(f)   # keeps the signature and docstring, which @function_tool turns into the tool schema
        def run(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            call = dict(bound.arguments)
            value = value_usd(call) if callable(value_usd) else value_usd
            cs.wait_if_paused()
            return cs.tool(name, call, fn=lambda **final: f(**final), value_usd=value, fail_closed=fail_closed)

        return run

    return deco(fn) if callable(fn) else deco


__all__ = ["CloudSentinelProcessor", "instrument", "guard"]