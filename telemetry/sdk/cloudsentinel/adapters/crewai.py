"""
CrewAI adapter: one call, no change to your crew code.   Owner: Fojle.

    import cloudsentinel as cs
    from cloudsentinel.adapters.crewai import instrument

    cs.init(agent_id="crew-support")
    instrument(value_usd={"issue_refund": lambda a: a["amount"] / 122}, fail_closed=("issue_refund",))
    crew.kickoff(inputs={...})

What you get (CONTRACTS §4), from CrewAI's event bus and its blocking hooks:
  crew kickoff        → `invoke_agent` span (task, success/failure)
  every crew task     → `graph_node {agent role}` span (step = order in the run, changed = task + output preview)
  every LLM call      → `chat {model}` span with token usage
  every tool call     → `execute_tool {tool}` span, and BEFORE it runs: the CloudSentinel tool gate
                        (deny → blocked, rewrite → arguments changed in place, approval → waits for a human)
  before every LLM    → cs.wait_if_paused(): a paused agent waits, a killed one is blocked

CrewAI runs event handlers on a thread pool, so (1) `kickoff()` can return before the last handlers ran: call
`flush()` from this module after a kickoff (it waits for CrewAI's event bus, then exports); (2) a "done" event can
be handled before its "start": the listener keeps early completions and applies them when the start arrives.

Install CrewAI in the AGENT's environment (its own venv/container): `pip install "cloudsentinel[crewai]"`.
Note: crewai 1.x pins mcp<2 while the CloudSentinel brain needs mcp>=2, so don't install it next to the brain.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Callable, Iterable, Optional, Union

from crewai.events import BaseEventListener, crewai_event_bus
from crewai.events.types.crew_events import CrewKickoffCompletedEvent, CrewKickoffFailedEvent, CrewKickoffStartedEvent
from crewai.events.types.llm_events import LLMCallCompletedEvent, LLMCallFailedEvent, LLMCallStartedEvent
from crewai.events.types.task_events import TaskCompletedEvent, TaskFailedEvent, TaskStartedEvent
from crewai.events.types.tool_usage_events import ToolUsageErrorEvent, ToolUsageFinishedEvent, ToolUsageStartedEvent
from crewai.hooks import register_before_llm_call_hook, register_before_tool_call_hook

import cloudsentinel as cs

log = logging.getLogger("cloudsentinel.crewai")
ValueMap = dict[str, Union[float, Callable[[dict], float]]]


def _key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


class CloudSentinelListener(BaseEventListener):
    """CrewAI events → CloudSentinel spans. Never raises into CrewAI."""

    def __init__(self) -> None:
        self._spans: dict[str, Any] = {}
        self._crew: Optional[Any] = None
        self._step = 0
        self._decisions: dict[str, str] = {}   # tool name → last gate decision (set by the hook)
        self._early: dict[str, tuple[Optional[dict], Any, Callable[[], None]]] = {}  # done before start
        self._lock = threading.Lock()
        super().__init__()

    # small helpers
    def _open(self, key: str, name: str, op: str, attrs: dict, parent: Any = None) -> None:
        span = cs.start_span(name, op, attrs, parent=parent if parent is not None else self._crew)
        with self._lock:
            early = self._early.pop(key, None)
            if early is None:
                self._spans[key] = span
        if early is not None:  # its "done" event was handled first: close it right away
            self._end(span, early[0], early[1])

    @staticmethod
    def _end(span: Any, attrs: Optional[dict], error: Any) -> None:
        for k, v in (attrs or {}).items():
            span.set_attribute(k, v)
        cs.end_span(span, error)

    def _close(self, key: str, error: Any = None, attrs: Optional[dict] = None,
               start_late: Optional[Callable[[], None]] = None) -> None:
        with self._lock:
            span = self._spans.pop(key, None)
            if span is None:  # the start hasn't been handled yet (thread pool): keep the result for it
                self._early[key] = (attrs, error, start_late or (lambda: None))
                return
        self._end(span, attrs, error)

    def drain(self) -> None:
        """Completions whose start never arrived (e.g. a custom LLM without llm_call_context): record them anyway."""
        with self._lock:
            keys = list(self._early)
        for key in keys:
            entry = self._early.get(key)
            if entry is not None:
                entry[2]()                  # opens the span from the done event; _open applies the stored result
            with self._lock:
                self._early.pop(key, None)  # never retry a start that failed

    def _task_span(self, task_id: Any) -> Any:
        return self._spans.get(_key("task", task_id)) if task_id else None

    def setup_listeners(self, bus: Any) -> None:
        def safe(fn: Callable) -> Callable:
            def run(source: Any, event: Any) -> None:
                try:
                    fn(event)
                except Exception:  # telemetry must never break the crew
                    log.exception("cloudsentinel crewai handler failed")
            return run

        # crew = one task
        @safe
        def crew_start(e: CrewKickoffStartedEvent) -> None:
            self._step = 0
            self._crew = cs.start_span(f"invoke_agent {cs._s.agent_id}", "invoke_agent", {
                cs.AGENT_NAME: cs._s.agent_id, cs.AGENT_ID: cs._s.agent_id, cs.CS_TASK_ID: uuid.uuid4().hex[:12],
                cs.CS_TASK_STATUS: "abandoned"})

        @safe
        def crew_done(e: Any) -> None:
            ok = isinstance(e, CrewKickoffCompletedEvent)
            span, self._crew = self._crew, None
            if span is not None:
                span.set_attribute(cs.CS_TASK_STATUS, "success" if ok else "failure")
                cs.end_span(span, None if ok else str(getattr(e, "error", "failed"))[:100])

        # crew tasks = nodes of the run
        @safe
        def task_start(e: TaskStartedEvent) -> None:
            self._step += 1
            role = str(e.agent_role or getattr(getattr(e.task, "agent", None), "role", "") or "agent")
            self._open(_key("task", e.task_id), f"graph_node {role}", "graph_node", {
                cs.CS_NODE: role, cs.CS_NODE_STEP: self._step, cs.CS_NODE_FRAMEWORK: "crewai"})

        @safe
        def task_done(e: Any) -> None:
            output = getattr(e, "output", None)
            delta = {"task": e.task_name or "", "output": getattr(output, "raw", output) if output is not None else ""}
            err = getattr(e, "error", None) if isinstance(e, TaskFailedEvent) else None
            self._close(_key("task", e.task_id), err,
                        {cs.CS_NODE_STATE_DELTA: json.dumps(cs.preview_delta(delta), ensure_ascii=False)})

        # LLM calls
        @safe
        def llm_start(e: Any) -> None:
            msgs = e.messages if isinstance(e.messages, list) else [{"content": e.messages}]
            last = msgs[-1] if msgs else {}
            prompt = str(last.get("content", "") if isinstance(last, dict) else last)
            attrs = {cs.PROVIDER: "crewai", cs.REQUEST_MODEL: str(e.model or "unknown")}
            if prompt:
                attrs[cs.CS_PROMPT_HASH] = cs._prompt_hash(prompt)
                if cs._s.capture_prompts:
                    attrs[cs.CS_PROMPT_PREVIEW] = prompt[:200]
            self._open(_key("llm", e.call_id), f"chat {e.model}", "chat", attrs, parent=self._task_span(e.task_id))

        @safe
        def llm_done(e: Any) -> None:
            usage = getattr(e, "usage", None) or {}
            attrs = {cs.INPUT_TOKENS: int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                     cs.OUTPUT_TOKENS: int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)}
            key = _key("llm", e.call_id)
            self._close(key, getattr(e, "error", None) if isinstance(e, LLMCallFailedEvent) else None, attrs,
                        start_late=lambda: llm_start(None, e))

        # tools
        @safe
        def tool_start(e: ToolUsageStartedEvent) -> None:
            args = e.tool_args if isinstance(e.tool_args, (dict, str)) else str(e.tool_args)
            self._open(_key("tool", e.event_id), f"execute_tool {e.tool_name}", "execute_tool", {
                cs.TOOL_NAME: e.tool_name, cs.TOOL_CALL_ID: str(e.event_id)[:12],
                cs.CS_TOOL_ARGS: json.dumps(args, default=str)[:500],
                cs.CS_TOOL_DECISION: self._decisions.get(e.tool_name, "allow")}, parent=self._task_span(e.task_id))

        @safe
        def tool_done(e: Any) -> None:
            key = _key("tool", e.started_event_id)
            failed = isinstance(e, ToolUsageErrorEvent) or getattr(e, "failure", False)
            self._close(key, getattr(e, "error", None) or ("tool failed" if failed else None),
                        start_late=lambda: tool_start(None, ToolUsageStartedEvent.model_construct(**{
                            k: getattr(e, k, None) for k in ("tool_name", "tool_args", "task_id", "agent_role")},
                            event_id=e.started_event_id)))

        for event, handler in [(CrewKickoffStartedEvent, crew_start), (CrewKickoffCompletedEvent, crew_done),
                               (CrewKickoffFailedEvent, crew_done), (TaskStartedEvent, task_start),
                               (TaskCompletedEvent, task_done), (TaskFailedEvent, task_done),
                               (LLMCallStartedEvent, llm_start), (LLMCallCompletedEvent, llm_done),
                               (LLMCallFailedEvent, llm_done), (ToolUsageStartedEvent, tool_start),
                               (ToolUsageFinishedEvent, tool_done), (ToolUsageErrorEvent, tool_done)]:
            bus.on(event)(handler)


_listener: Optional[CloudSentinelListener] = None


def instrument(value_usd: Optional[ValueMap] = None, fail_closed: Iterable[str] = (), gate_tools: bool = True,
               pause_check: bool = True) -> CloudSentinelListener:
    """Turn on CloudSentinel for every crew in this process. Safe to call more than once."""
    global _listener
    if _listener is not None:
        return _listener
    _listener = listener = CloudSentinelListener()
    values, closed = dict(value_usd or {}), set(fail_closed)

    if gate_tools:
        def gate_hook(ctx: Any) -> Optional[bool]:
            name, args = str(ctx.tool_name), dict(ctx.tool_input or {})
            value = values.get(name)
            try:
                value = value(args) if callable(value) else value
            except Exception:
                value = None
            decision, final = cs.gate(name, args, value, fail_closed=name in closed)
            listener._decisions[name] = decision
            if decision in ("deny", "timeout"):
                log.warning("CloudSentinel blocked %s (%s)", name, decision)
                # CrewAI emits no tool events for a blocked call, so record the blocked attempt ourselves
                task_span = listener._task_span(getattr(getattr(ctx, "task", None), "id", None))
                span = cs.start_span(f"execute_tool {name}", "execute_tool", {
                    cs.TOOL_NAME: name, cs.TOOL_CALL_ID: uuid.uuid4().hex[:12], cs.CS_TOOL_DECISION: decision,
                    cs.CS_TOOL_ARGS: json.dumps(args, default=str)[:500],
                    **({cs.CS_TOOL_VALUE_USD: float(value)} if value is not None else {})},
                    parent=task_span if task_span is not None else listener._crew)
                cs.end_span(span, f"tool_{decision}")
                return False
            if decision == "rewrite":
                ctx.tool_input.clear()           # CrewAI wants the dict changed in place
                ctx.tool_input.update(final)
            return None
        register_before_tool_call_hook(gate_hook)

    if pause_check:
        def pause_hook(ctx: Any) -> Optional[bool]:
            try:
                cs.wait_if_paused()
            except cs.AgentKilled:
                return False   # killed: block every further LLM call
            return None
        register_before_llm_call_hook(pause_hook)
    return listener


def flush(timeout: float = 10.0) -> None:
    """Call after crew.kickoff(): wait until CrewAI's event handlers ran, then export the spans."""
    try:
        crewai_event_bus.flush(timeout=timeout)
    except Exception:  # never break the caller over telemetry
        log.exception("crewai event bus flush failed")
    if _listener is not None:
        _listener.drain()
    cs.flush()


__all__ = ["instrument", "flush", "CloudSentinelListener"]
