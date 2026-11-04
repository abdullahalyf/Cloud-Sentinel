"""
LangGraph adapter: one callback handler, no change to your graph code.   Owner: Fojle.

    import cloudsentinel as cs
    from cloudsentinel.adapters.langgraph import CloudSentinelCallback, guard

    cs.init(agent_id="lg-refund")
    tools = [guard(lookup_order), guard(issue_refund, value_usd=lambda a: a["amount"] / 122, fail_closed=True)]
    app = graph.compile()
    app.invoke(state, config={"callbacks": [CloudSentinelCallback()]})

What you get (CONTRACTS §4):
  graph run          → `invoke_agent` span (task, success/failure)
  every node run     → `graph_node {node}` span with step, the state delta it returned, and where it routed next
  every chat model   → `chat {model}` span with token usage (feeds loop detection, budgets, ROI)
  every tool         → `execute_tool {tool}` span; tools wrapped with guard() also go through the tool gate
  before every node  → cs.wait_if_paused(): a paused agent stops between nodes, a killed one raises AgentKilled
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Callable, Optional, Union
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import context as otel_context
from opentelemetry import trace
from langchain_core.tools import BaseTool, StructuredTool

import cloudsentinel as cs

log = logging.getLogger("cloudsentinel.langgraph")

ValueFn = Union[float, Callable[[dict], float], None]
ROUTER_NAMES = {"RunnableCallable", "branch", "Branch"}  # what LangGraph calls a conditional-edge router


class CloudSentinelCallback(BaseCallbackHandler):
    """LangChain/LangGraph callback → CloudSentinel spans. Telemetry errors are logged, never raised;
    only AgentKilled (from the pause check) is allowed to stop the graph."""

    raise_error = True      # so AgentKilled can stop the run; every other error is caught below
    run_inline = True       # keep callbacks on the graph's thread (pause check must block the node)

    def __init__(self, task_name: str = "", pause_check: bool = True):
        self.task_name, self.pause_check = task_name, pause_check
        self._spans: dict[UUID, Any] = {}       # run_id → open span
        self._parent: dict[UUID, Optional[UUID]] = {}
        self._node_of: dict[UUID, str] = {}     # run_id of a node run → node name
        self._router: set[UUID] = set()         # runs that look like conditional-edge routers
        self._ctx_tokens: dict[UUID, Any] = {}  # node run → OTel context token (node span is "current" inside it)
        self._seen_nodes: set[str] = {"__end__"}
        self._lock = threading.Lock()

    # ── helpers ──
    def _safe(self, fn: Callable, *args) -> None:
        try:
            fn(*args)
        except cs.AgentKilled:
            raise
        except Exception:  # telemetry must never break the agent
            log.exception("cloudsentinel callback failed")

    def _ancestor_span(self, run_id: Optional[UUID]) -> Any:
        while run_id is not None:
            if run_id in self._spans:
                return self._spans[run_id]
            run_id = self._parent.get(run_id)
        return None

    def _open(self, run_id: UUID, parent_run_id: Optional[UUID], name: str, operation: str, attrs: dict) -> None:
        with self._lock:
            self._parent[run_id] = parent_run_id
            parent = self._ancestor_span(parent_run_id)
            self._spans[run_id] = cs.start_span(name, operation, attrs, parent=parent)

    def _close(self, run_id: UUID, error: Any = None, attrs: Optional[dict] = None) -> None:
        with self._lock:
            span = self._spans.pop(run_id, None)
            self._node_of.pop(run_id, None)
            token = self._ctx_tokens.pop(run_id, None)
        if token is not None:
            try:
                otel_context.detach(token)
            except Exception:  # detached from another thread/context: harmless for telemetry
                pass
        if span is not None:
            for key, value in (attrs or {}).items():
                span.set_attribute(key, value)
            cs.end_span(span, error)

    # ── graph + nodes ──
    def on_chain_start(self, serialized: Optional[dict], inputs: Any, *, run_id: UUID,
                       parent_run_id: Optional[UUID] = None, metadata: Optional[dict] = None, **kw: Any) -> None:
        self._safe(self._chain_start, run_id, parent_run_id, kw.get("name") or (serialized or {}).get("name", ""),
                   metadata or {}, kw.get("tags") or [])

    def _chain_start(self, run_id: UUID, parent_run_id: Optional[UUID], name: str, metadata: dict,
                     tags: list) -> None:
        if parent_run_id is None:  # the graph itself → one task
            self._open(run_id, None, f"invoke_agent {cs._s.agent_id}", "invoke_agent", {
                cs.AGENT_NAME: cs._s.agent_id, cs.AGENT_ID: cs._s.agent_id, cs.CS_TASK_ID: uuid.uuid4().hex[:12],
                cs.CS_TASK_STATUS: "abandoned"})
            return
        node = metadata.get("langgraph_node")
        if node and name == node:  # the node run (inner runnables share the metadata but not the name)
            if self.pause_check:
                cs.wait_if_paused()  # may block (paused) or raise AgentKilled
            self._open(run_id, parent_run_id, f"graph_node {node}", "graph_node", {
                cs.CS_NODE: node, cs.CS_NODE_STEP: metadata.get("langgraph_step"), cs.CS_NODE_FRAMEWORK: "langgraph"})
            with self._lock:
                self._node_of[run_id] = node
                self._seen_nodes.add(node)
                # make the node span current, so cs.tool()/cs.llm_call() inside the node nest under it
                self._ctx_tokens[run_id] = otel_context.attach(trace.set_span_in_context(self._spans[run_id]))
        else:
            with self._lock:
                self._parent[run_id] = parent_run_id
                # LangGraph runs a node as a sequence [node fn, write, router]; the router is tagged seq:step:N
                if parent_run_id in self._node_of and (name in ROUTER_NAMES or any(
                        str(t).startswith("seq:step:") for t in tags)):
                    self._router.add(run_id)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        self._safe(self._chain_end, outputs, run_id, parent_run_id)

    def _chain_end(self, outputs: Any, run_id: UUID, parent_run_id: Optional[UUID]) -> None:
        if run_id in self._node_of:
            update, goto = outputs, ""
            if hasattr(outputs, "update") and hasattr(outputs, "goto"):  # LangGraph Command(update=..., goto=...)
                update, goto = outputs.update, outputs.goto
            span = self._spans.get(run_id)
            if span is not None:
                span.set_attribute(cs.CS_NODE_STATE_DELTA, json.dumps(cs.preview_delta(update), ensure_ascii=False))
                if goto:
                    span.set_attribute(cs.CS_NODE_NEXT, str(goto))
            self._close(run_id)
        elif self._parent.get(run_id) is None and run_id in self._spans:  # graph finished
            self._close(run_id, attrs={cs.CS_TASK_STATUS: "success"})
        else:
            # a router inside a node returns the next node's name: remember it on the node span
            node_span = self._spans.get(parent_run_id) if parent_run_id in self._node_of else None
            targets = [outputs] if isinstance(outputs, str) else outputs if isinstance(outputs, list) else []
            is_router = run_id in self._router or (targets and all(t in self._seen_nodes for t in targets))
            if node_span is not None and targets and is_router and all(isinstance(t, str) for t in targets):
                node_span.set_attribute(cs.CS_NODE_NEXT, ",".join(targets))
            with self._lock:
                self._parent.pop(run_id, None)
                self._router.discard(run_id)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        def _err() -> None:
            is_task = self._parent.get(run_id) is None and run_id in self._spans
            self._close(run_id, error, {cs.CS_TASK_STATUS: "failure"} if is_task else None)
        self._safe(_err)

    # ── models ──
    def on_chat_model_start(self, serialized: Optional[dict], messages: list, *, run_id: UUID,
                            parent_run_id: Optional[UUID] = None, metadata: Optional[dict] = None, **kw: Any) -> None:
        last = messages[0][-1] if messages and messages[0] else None
        prompt = str(getattr(last, "content", last) or "")
        self._safe(self._llm_start, run_id, parent_run_id, serialized or {}, metadata or {}, kw, prompt)

    def on_llm_start(self, serialized: Optional[dict], prompts: list[str], *, run_id: UUID,
                     parent_run_id: Optional[UUID] = None, metadata: Optional[dict] = None, **kw: Any) -> None:
        self._safe(self._llm_start, run_id, parent_run_id, serialized or {}, metadata or {}, kw,
                   prompts[-1] if prompts else "")

    def _llm_start(self, run_id: UUID, parent_run_id: Optional[UUID], serialized: dict, metadata: dict, kw: dict,
                   prompt: str) -> None:
        params = kw.get("invocation_params") or {}
        model = str(metadata.get("ls_model_name") or params.get("model") or params.get("model_name")
                    or serialized.get("name") or "unknown")
        provider = str(metadata.get("ls_provider") or params.get("_type") or "langchain")
        attrs = {cs.PROVIDER: provider, cs.REQUEST_MODEL: model}
        if prompt:
            attrs[cs.CS_PROMPT_HASH] = cs._prompt_hash(prompt)
            if cs._s.capture_prompts:
                attrs[cs.CS_PROMPT_PREVIEW] = prompt[:200]
        self._open(run_id, parent_run_id, f"chat {model}", "chat", attrs)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kw: Any) -> None:
        self._safe(lambda: self._close(run_id, attrs=_usage(response)))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        self._safe(self._close, run_id, error)

    # ── tools (telemetry only; use guard() for the gate) ──
    def on_tool_start(self, serialized: Optional[dict], input_str: str, *, run_id: UUID,
                      parent_run_id: Optional[UUID] = None, inputs: Optional[dict] = None, **kw: Any) -> None:
        name = str((serialized or {}).get("name") or kw.get("name") or "tool")
        if name in _GUARDED:  # guard() already emits a gated execute_tool span
            with self._lock:
                self._parent[run_id] = parent_run_id
            return
        args = json.dumps(inputs if inputs is not None else input_str, default=str)[:500]
        self._safe(self._open, run_id, parent_run_id, f"execute_tool {name}", "execute_tool", {
            cs.TOOL_NAME: name, cs.TOOL_CALL_ID: str(run_id)[:12], cs.CS_TOOL_ARGS: args, cs.CS_TOOL_DECISION: "allow"})

    def on_tool_end(self, output: Any, *, run_id: UUID, **kw: Any) -> None:
        self._safe(self._close, run_id)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        self._safe(self._close, run_id, error)


def _usage(response: Any) -> dict:
    """Token usage from an LLMResult: message.usage_metadata first, then llm_output (OpenAI/Anthropic style)."""
    tin = tout = 0
    try:
        msg = response.generations[0][0].message
        meta = getattr(msg, "usage_metadata", None) or {}
        tin, tout = int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0)
    except (AttributeError, IndexError, TypeError):
        pass
    if not (tin or tout):
        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or \
                (getattr(response, "llm_output", None) or {}).get("usage") or {}
        tin = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        tout = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return {cs.INPUT_TOKENS: tin, cs.OUTPUT_TOKENS: tout}


_GUARDED: set[str] = set()


def guard(tool: BaseTool, value_usd: ValueFn = None, fail_closed: bool = False) -> StructuredTool:
    """Wrap a LangChain tool so every call goes through the CloudSentinel tool gate (allow/deny/rewrite/approval).
    value_usd: money at risk (number, or a function of the args) — used for approvals and ROI.
    Use fail_closed=True for money-moving tools. A denied call raises cs.ToolDenied."""
    _GUARDED.add(tool.name)

    def run(**kwargs: Any) -> Any:
        value = value_usd(kwargs) if callable(value_usd) else value_usd
        return cs.tool(tool.name, kwargs, fn=lambda **final: tool.invoke(final), value_usd=value,
                       fail_closed=fail_closed)

    return StructuredTool.from_function(func=run, name=tool.name, description=tool.description,
                                        args_schema=tool.args_schema)


__all__ = ["CloudSentinelCallback", "guard"]
