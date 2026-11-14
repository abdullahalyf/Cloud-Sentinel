"""
cloudsentinel — the agent SDK (CONTRACTS §10).   Owner: Fojle.

    import cloudsentinel as cs
    cs.init(agent_id="beta")
    with cs.task("track order 4471") as t:
        mem = cs.memory.get()
        with cs.llm_call(model="claude-haiku-5-5", provider="anthropic", prompt=p) as call:
            ...                                          # call your LLM
            call.record(input_tokens=..., output_tokens=...)
        cs.tool("issue_refund", {"amount": 500}, fn=issue_refund, value_usd=4.1)
        with cs.node("lookup_order", step=1) as n:     # graph_node span (framework adapters do this for you)
            n.changed({"order_status": "refunded"})
        t.success()

Framework adapters (LangGraph, CrewAI) live in telemetry/adapters/ and are built on node(), gate(),
start_span()/end_span() and wait_if_paused() below.

Telemetry = OpenTelemetry GenAI spans exported over OTLP/HTTP (works with any OTel backend).
Control  = HTTP calls to the CloudSentinel C2 API (tool gate + external memory).
Dependencies: opentelemetry-sdk + opentelemetry-exporter-otlp-proto-http (if missing, telemetry is a no-op).
No imports from the rest of the repo, so this folder can be copied into any agent image.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Iterator, Optional

log = logging.getLogger("cloudsentinel")

# Attribute names — must equal shared.contracts.Attr (checked by shared/tests/test_contracts.py)
OPERATION, PROVIDER, REQUEST_MODEL = "gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model"
INPUT_TOKENS, OUTPUT_TOKENS = "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens"
AGENT_NAME, AGENT_ID, TOOL_NAME, TOOL_CALL_ID = "gen_ai.agent.name", "gen_ai.agent.id", "gen_ai.tool.name", "gen_ai.tool.call.id"
ERROR_TYPE = "error.type"
CS_AGENT_ID, CS_RUNTIME = "cloudsentinel.agent.id", "cloudsentinel.runtime"
CS_TASK_ID, CS_TASK_STATUS = "cloudsentinel.task.id", "cloudsentinel.task.status"
CS_PROMPT_PREVIEW, CS_PROMPT_HASH = "cloudsentinel.prompt.preview", "cloudsentinel.prompt.hash"
CS_TOOL_ARGS, CS_TOOL_DECISION, CS_TOOL_VALUE_USD = ("cloudsentinel.tool.args", "cloudsentinel.tool.decision",
                                                    "cloudsentinel.tool.value_usd")
CS_NODE, CS_NODE_STEP = "cloudsentinel.node.name", "cloudsentinel.node.step"
CS_NODE_FRAMEWORK, CS_NODE_STATE_DELTA = "cloudsentinel.node.framework", "cloudsentinel.node.state_delta"
CS_NODE_NEXT = "cloudsentinel.node.next"
MAX_DELTA_KEYS, MAX_PREVIEW = 8, 60


class ToolDenied(Exception):
    """The tool call was denied by policy or a human (or timed out waiting for approval)."""


class AgentKilled(Exception):
    """CloudSentinel killed this agent: stop working (raised by wait_if_paused)."""


# Defaults use 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 (::1) first, the servers
# listen on IPv4 only, and every call waits ~2 s for the refused connection before falling back.
class _State:
    agent_id = "agent"
    api_url = "http://127.0.0.1:8000"
    token = ""
    capture_prompts = True
    tracer: Any = None
    provider: Any = None
    approval_timeout = 120.0


_s = _State()


def _prompt_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text.strip().lower()).encode()).hexdigest()[:12]


# ── setup ───────────────────────────────────────────────────────────────────
def init(agent_id: Optional[str] = None, runtime: str = "local", api_url: Optional[str] = None,
         otlp_endpoint: Optional[str] = None) -> None:
    """Call once at start-up. Values default to env vars CS_AGENT_ID, CS_API_URL, OTEL_EXPORTER_OTLP_ENDPOINT."""
    _s.agent_id = agent_id or os.getenv("CS_AGENT_ID") or os.getenv("AGENT_NAME") or "agent"
    _s.api_url = (api_url or os.getenv("CS_API_URL", "http://127.0.0.1:8000")).rstrip("/")
    _s.token = os.getenv("CS_API_TOKEN", "")
    _s.capture_prompts = os.getenv("CS_CAPTURE_PROMPTS", "true").lower() in ("1", "true", "yes", "on")
    _s.approval_timeout = float(os.getenv("TOOL_APPROVAL_TIMEOUT_SECONDS", "120"))
    endpoint = (otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")).rstrip("/")
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create(
            {"service.name": _s.agent_id, CS_AGENT_ID: _s.agent_id, CS_RUNTIME: runtime}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"),
                                                       schedule_delay_millis=500))
        _s.provider, _s.tracer = provider, provider.get_tracer("cloudsentinel")
    except ImportError:
        from opentelemetry import trace  # API only → no-op tracer

        _s.tracer = trace.get_tracer("cloudsentinel")
        log.warning("opentelemetry-sdk not installed: telemetry disabled")


def flush() -> None:
    if _s.provider:
        _s.provider.force_flush()


def _tracer():
    if _s.tracer is None:
        init()
    return _s.tracer


# ── spans ───────────────────────────────────────────────────────────────────
class _Task:
    def __init__(self, span):
        self.span, self.status = span, "abandoned"

    def success(self) -> None:
        self.status = "success"

    def failure(self, reason: str = "") -> None:
        self.status = "failure"
        if reason:
            self.span.set_attribute(ERROR_TYPE, reason[:100])


@contextlib.contextmanager
def task(description: str = "", task_id: Optional[str] = None) -> Iterator[_Task]:
    """One unit of agent work → an `invoke_agent` span."""
    with _tracer().start_as_current_span(f"invoke_agent {_s.agent_id}") as span:
        span.set_attribute(OPERATION, "invoke_agent")
        span.set_attribute(AGENT_NAME, _s.agent_id)
        span.set_attribute(AGENT_ID, _s.agent_id)
        span.set_attribute(CS_TASK_ID, task_id or uuid.uuid4().hex[:12])
        t = _Task(span)
        try:
            yield t
        except Exception as exc:
            t.failure(type(exc).__name__)
            raise
        finally:
            span.set_attribute(CS_TASK_STATUS, t.status)


class _Call:
    def __init__(self, span):
        self.span = span

    def record(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.span.set_attribute(INPUT_TOKENS, int(input_tokens))
        self.span.set_attribute(OUTPUT_TOKENS, int(output_tokens))


@contextlib.contextmanager
def llm_call(model: str, provider: str = "anthropic", prompt: str = "") -> Iterator[_Call]:
    """One model call → a `chat` span. Call .record(...) with the token usage."""
    with _tracer().start_as_current_span(f"chat {model}") as span:
        span.set_attribute(OPERATION, "chat")
        span.set_attribute(PROVIDER, provider)
        span.set_attribute(REQUEST_MODEL, model)
        span.set_attribute(CS_AGENT_ID, _s.agent_id)
        if prompt and _s.capture_prompts:
            span.set_attribute(CS_PROMPT_PREVIEW, prompt[:200])
        if prompt:
            span.set_attribute(CS_PROMPT_HASH, _prompt_hash(prompt))
        yield _Call(span)


def preview_delta(update: Any) -> dict:
    """What a node changed, as {key: short text} (≤8 keys, ≤60 chars each), safe to put on a span."""
    if not isinstance(update, dict):
        update = {"value": update} if update is not None else {}
    out = {}
    for key in list(update)[:MAX_DELTA_KEYS]:
        value = update[key]
        if isinstance(value, list):
            text = f"{len(value)} items" + (f", last: {value[-1]!s:.40}" if value else "")
        else:
            text = str(getattr(value, "content", value))
        out[str(key)[:40]] = text if len(text) <= MAX_PREVIEW else text[:MAX_PREVIEW - 1] + "…"
    if len(update) > MAX_DELTA_KEYS:
        out["…"] = f"+{len(update) - MAX_DELTA_KEYS} more keys"
    return out


class _Node:
    def __init__(self, span):
        self.span = span

    def changed(self, update: Any) -> None:
        """Record the state change this node made (e.g. the dict a LangGraph node returns)."""
        self.span.set_attribute(CS_NODE_STATE_DELTA, json.dumps(preview_delta(update), ensure_ascii=False))


@contextlib.contextmanager
def node(name: str, step: Optional[int] = None, framework: str = "custom") -> Iterator[_Node]:
    """One step of a graph/crew (LangGraph node, CrewAI task) → a `graph_node` span."""
    span = start_span(f"graph_node {name}", "graph_node", {CS_NODE: name, CS_NODE_FRAMEWORK: framework,
                                                           **({CS_NODE_STEP: int(step)} if step is not None else {})})
    from opentelemetry import trace

    with trace.use_span(span, end_on_exit=True):
        yield _Node(span)


def start_span(name: str, operation: str, attributes: Optional[dict] = None, parent: Any = None) -> Any:
    """Open a span that you close later with end_span() (for callback-style framework hooks)."""
    from opentelemetry import trace

    ctx = trace.set_span_in_context(parent) if parent is not None else None
    span = _tracer().start_span(name, context=ctx)
    span.set_attribute(OPERATION, operation)
    span.set_attribute(CS_AGENT_ID, _s.agent_id)
    for key, value in (attributes or {}).items():
        if value is not None:
            span.set_attribute(key, value)
    return span


def end_span(span: Any, error: Optional[BaseException | str] = None) -> None:
    if span is None:
        return
    if error is not None:
        from opentelemetry.trace import Status, StatusCode

        span.set_attribute(ERROR_TYPE, (type(error).__name__ if isinstance(error, BaseException) else str(error))[:100])
        span.set_status(Status(StatusCode.ERROR))
    span.end()


# ── C2 API client (stdlib only) ─────────────────────────────────────────────
def _api(method: str, path: str, body: Optional[dict] = None, timeout: float = 5.0) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_s.api_url + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-CS-Token": _s.token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None


def tool(name: str, args: dict, fn: Callable[..., Any], value_usd: Optional[float] = None,
         fail_closed: bool = False) -> Any:
    """
    Ask the gate, then run fn(**args) inside an `execute_tool` span.
    allow → fn(**args) · rewrite → fn(**final_args) · deny/timeout → raises ToolDenied.
    If the API is unreachable: runs the tool (fail open) unless fail_closed=True.
    """
    with _tracer().start_as_current_span(f"execute_tool {name}") as span:
        span.set_attribute(OPERATION, "execute_tool")
        span.set_attribute(TOOL_NAME, name)
        span.set_attribute(TOOL_CALL_ID, uuid.uuid4().hex[:12])
        span.set_attribute(CS_AGENT_ID, _s.agent_id)
        span.set_attribute(CS_TOOL_ARGS, json.dumps(args)[:500])
        if value_usd is not None:
            span.set_attribute(CS_TOOL_VALUE_USD, float(value_usd))
        decision, final_args = _gate(name, args, value_usd, fail_closed)
        span.set_attribute(CS_TOOL_DECISION, decision)
        if decision in ("deny", "timeout"):
            span.set_attribute(ERROR_TYPE, f"tool_{decision}")
            raise ToolDenied(f"{name} was {decision}")
        return fn(**(final_args if decision == "rewrite" else args))


def gate(name: str, args: dict, value_usd: Optional[float] = None, fail_closed: bool = False) -> tuple[str, dict]:
    """Ask CloudSentinel before running a tool, without running it. Returns (decision, final_args).
    decision: allow | deny | rewrite | timeout. Blocks while a human decides (pending)."""
    return _gate(name, args, value_usd, fail_closed)


def wait_if_paused(poll_seconds: float = 1.0, max_wait: Optional[float] = None) -> None:
    """Cooperative pause for agents without a container (local process, notebook):
    blocks while CloudSentinel has this agent paused, raises AgentKilled if it was killed.
    Fails open (returns at once) if the API is unreachable."""
    started = time.time()
    while True:
        try:
            status, body = _api("GET", f"/v1/agents/{_s.agent_id}", timeout=2.0)
        except (urllib.error.URLError, OSError):
            return
        state = ((body or {}).get("agent") or {}).get("state") if status == 200 else None
        if state == "killed":
            raise AgentKilled(f"{_s.agent_id} was killed by CloudSentinel")
        if state != "paused" or (max_wait is not None and time.time() - started > max_wait):
            return
        time.sleep(poll_seconds)


def _gate(name: str, args: dict, value_usd: Optional[float], fail_closed: bool) -> tuple[str, dict]:
    try:
        status, call = _api("POST", f"/v1/agents/{_s.agent_id}/tool-calls",
                            {"tool_name": name, "args": args, "value_usd": value_usd})
    except (urllib.error.URLError, OSError) as exc:
        log.warning("tool gate unreachable (%s): %s", exc, "denying" if fail_closed else "allowing")
        return ("deny" if fail_closed else "allow"), args
    if status != 200 or not call:
        return ("deny" if fail_closed else "allow"), args
    deadline = time.time() + _s.approval_timeout
    while call["decision"] == "pending" and time.time() < deadline:
        time.sleep(1.0)
        _, latest = _api("GET", f"/v1/tool-calls/{call['id']}")
        call = latest or call
    decision = call["decision"] if call["decision"] != "pending" else "timeout"
    return decision, call.get("final_args") or args


class _Memory:
    """External memory stored by CloudSentinel, so a human can fix it while the agent is paused."""

    def __init__(self):
        self.version: Optional[int] = None

    def get(self) -> dict:
        try:
            status, row = _api("GET", f"/v1/agents/{_s.agent_id}/memory")
        except (urllib.error.URLError, OSError):
            return {}
        if status != 200 or not row:
            self.version = None
            return {}
        self.version = row["version"]
        return row.get("content") or {}

    def set(self, content: dict, reason: str = "") -> bool:
        """Save memory. Returns False if a human changed it meanwhile (call get() again)."""
        try:
            status, row = _api("PUT", f"/v1/agents/{_s.agent_id}/memory",
                               {"content": content, "edited_by": "agent", "reason": reason,
                                "base_version": self.version})
        except (urllib.error.URLError, OSError):
            return False
        if status == 200 and row:
            self.version = row["version"]
            return True
        return False


memory = _Memory()

__all__ = ["init", "flush", "task", "llm_call", "tool", "memory", "node", "gate", "wait_if_paused", "preview_delta",
           "start_span", "end_span", "ToolDenied", "AgentKilled"]
