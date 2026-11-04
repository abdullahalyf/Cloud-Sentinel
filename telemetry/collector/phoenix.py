"""
Optional export to Arize Phoenix.   Owner: Fojle.

    CS_EXPORT_PHOENIX=true  PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006  python -m telemetry.collector
    docker compose --profile phoenix up -d        # starts Phoenix on :6006 and turns the export on

The collector stays the single endpoint agents send to. Every OTLP batch it receives is also forwarded
(in a background thread, so agents never wait) to Phoenix's OTLP/HTTP endpoint `{endpoint}/v1/traces`.

On the way out we add what Phoenix's UI understands (OpenInference conventions), keeping every original
attribute: the project name (resource `openinference.project.name`), the span kind (chat → LLM,
execute_tool → TOOL, invoke_agent → AGENT, graph_node → CHAIN), model, token counts, tool name and the
prompt preview. So Phoenix shows CloudSentinel agents as LLM/agent traces, while CloudSentinel keeps
doing the control part (pause, heal, kill) that Phoenix doesn't do.
If Phoenix is down, spans are dropped for Phoenix only: CloudSentinel itself is never affected.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Optional

log = logging.getLogger("telemetry.phoenix")

KIND = {"chat": "LLM", "execute_tool": "TOOL", "invoke_agent": "AGENT", "graph_node": "CHAIN"}
QUEUE_SIZE = 500          # batches; when Phoenix is slow we drop the oldest work, never block the collector


def _kv(key: str, value: Any):
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

    if isinstance(value, bool):
        return KeyValue(key=key, value=AnyValue(bool_value=value))
    if isinstance(value, int):
        return KeyValue(key=key, value=AnyValue(int_value=value))
    if isinstance(value, float):
        return KeyValue(key=key, value=AnyValue(double_value=value))
    return KeyValue(key=key, value=AnyValue(string_value=str(value)))


def _plain(any_value) -> Any:
    kind = any_value.WhichOneof("value")
    return getattr(any_value, kind) if kind else None


def enrich(request, project: str) -> None:
    """Add OpenInference attributes in place to an ExportTraceServiceRequest (protobuf message)."""
    for rs in request.resource_spans:
        if not any(a.key == "openinference.project.name" for a in rs.resource.attributes):
            rs.resource.attributes.append(_kv("openinference.project.name", project))
        for ss in rs.scope_spans:
            for span in ss.spans:
                a = {kv.key: _plain(kv.value) for kv in span.attributes}
                op = a.get("gen_ai.operation.name") or span.name.split(" ")[0]
                extra: dict[str, Any] = {}
                if op in KIND and "openinference.span.kind" not in a:
                    extra["openinference.span.kind"] = KIND[op]
                if op == "chat":
                    tin, tout = int(a.get("gen_ai.usage.input_tokens") or 0), int(a.get("gen_ai.usage.output_tokens") or 0)
                    extra.update({"llm.model_name": a.get("gen_ai.request.model", ""), "llm.token_count.prompt": tin,
                                  "llm.token_count.completion": tout, "llm.token_count.total": tin + tout,
                                  "llm.provider": a.get("gen_ai.provider.name", "")})
                    if a.get("cloudsentinel.prompt.preview"):
                        extra["input.value"] = a["cloudsentinel.prompt.preview"]
                elif op == "execute_tool":
                    extra["tool.name"] = a.get("gen_ai.tool.name", "")
                    if a.get("cloudsentinel.tool.args"):
                        extra["input.value"] = a["cloudsentinel.tool.args"]
                elif op == "graph_node" and a.get("cloudsentinel.node.state_delta"):
                    extra["output.value"] = a["cloudsentinel.node.state_delta"]
                for key, value in extra.items():
                    if key not in a and value not in ("", None):
                        span.attributes.append(_kv(key, value))


def to_phoenix_body(body: bytes, content_type: str, project: str) -> bytes:
    """Collector input (protobuf or OTLP JSON) → enriched protobuf for Phoenix."""
    from google.protobuf import json_format
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    request = ExportTraceServiceRequest()
    if "json" in content_type:
        json_format.Parse(body or b"{}", request, ignore_unknown_fields=True)
    else:
        request.ParseFromString(body)
    enrich(request, project)
    return request.SerializeToString()


class PhoenixExporter:
    """Background forwarder. submit() never blocks and never raises."""

    def __init__(self, endpoint: str, project: str = "cloudsentinel", api_key: str = "", post: Any = None):
        self.url = endpoint.rstrip("/") + "/v1/traces"
        self.project = project
        self.headers = {"Content-Type": "application/x-protobuf"}
        if api_key:  # Phoenix Cloud / auth-enabled Phoenix
            self.headers["Authorization"] = f"Bearer {api_key}"
        self._post = post                          # injectable for tests
        self._queue: "queue.Queue[tuple[bytes, str]]" = queue.Queue(maxsize=QUEUE_SIZE)
        self.sent = self.failed = self.dropped = 0
        self._last_error_log = 0.0
        threading.Thread(target=self._run, name="phoenix-export", daemon=True).start()

    def submit(self, body: bytes, content_type: str) -> None:
        try:
            self._queue.put_nowait((body, content_type))
        except queue.Full:
            self.dropped += 1

    def _send(self, data: bytes) -> None:
        if self._post is not None:
            self._post(self.url, data, self.headers)
            return
        import httpx

        r = httpx.post(self.url, content=data, headers=self.headers, timeout=5.0)
        r.raise_for_status()

    def _run(self) -> None:
        while True:
            body, ctype = self._queue.get()
            try:
                self._send(to_phoenix_body(body, ctype, self.project))
                self.sent += 1
            except Exception as exc:
                self.failed += 1
                if time.time() - self._last_error_log > 30:   # don't flood the log while Phoenix is down
                    self._last_error_log = time.time()
                    log.warning("Phoenix export failed (%s); CloudSentinel keeps working", exc)
            finally:
                self._queue.task_done()

    def join(self, timeout: float = 5.0) -> None:
        """Wait until queued batches are sent (tests)."""
        end = time.time() + timeout
        while self._queue.unfinished_tasks and time.time() < end:
            time.sleep(0.01)


def from_settings(cfg) -> Optional[PhoenixExporter]:
    if not cfg.export_phoenix:
        return None
    log.info("Phoenix export ON → %s/v1/traces (project %s)", cfg.phoenix_endpoint, cfg.phoenix_project)
    return PhoenixExporter(cfg.phoenix_endpoint, cfg.phoenix_project, cfg.phoenix_api_key)
