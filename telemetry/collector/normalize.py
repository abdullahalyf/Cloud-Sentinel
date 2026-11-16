"""
OTLP → SpanRow (CONTRACTS §4). Works on the OTLP *JSON* shape (camelCase keys), which is also what
google.protobuf.json_format.MessageToDict() produces from the protobuf the standard exporter sends.
Pure functions, no network → easy to test.   Owner: Fojle.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from shared.contracts import Attr, SpanRow, prompt_hash
from shared.pricing import cost_usd

ERROR_CODES = (2, "2", "STATUS_CODE_ERROR")
MAX_SKEW_S = 30.0                          # a span start further than this from the collector's clock is skewed
SKEW_KEY = "cloudsentinel.clock_skew_s"


def attr_value(v: dict) -> Any:
    """{'stringValue': 'x'} → 'x'; {'intValue': '42'} → 42; arrays → lists."""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [attr_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def attrs_to_dict(attrs: list[dict] | None) -> dict[str, Any]:
    return {a["key"]: attr_value(a.get("value", {})) for a in (attrs or []) if "key" in a}


def to_hex(value: str) -> str:
    """OTLP JSON uses hex ids; MessageToDict gives base64. Accept both."""
    if not value:
        return ""
    if all(c in "0123456789abcdefABCDEF" for c in value) and len(value) in (16, 32):
        return value.lower()
    try:
        return base64.b64decode(value).hex()
    except (ValueError, TypeError):
        return value


def _operation(a: dict, name: str) -> str:
    op = a.get(Attr.OPERATION) or name.split(" ")[0]
    return {"text_completion": "chat", "generate_content": "chat"}.get(op, op)


def _with_skew(detail: str, skew: float) -> str:
    """Add cloudsentinel.clock_skew_s (agent clock minus collector clock, seconds) to the detail JSON."""
    if not skew:
        return detail
    try:
        d = json.loads(detail)
    except (TypeError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d[SKEW_KEY] = round(skew, 1)
    return json.dumps(d, ensure_ascii=False)


def normalize_span(span: dict, resource: dict[str, Any], now: float | None = None) -> SpanRow:
    a = attrs_to_dict(span.get("attributes"))
    name = span.get("name", "")
    agent_id = str(a.get(Attr.CS_AGENT_ID) or resource.get(Attr.CS_AGENT_ID) or a.get(Attr.AGENT_ID)
                   or resource.get(Attr.SERVICE_NAME) or "unknown")
    model = str(a.get(Attr.REQUEST_MODEL) or a.get("gen_ai.response.model") or "")
    tin, tout = int(a.get(Attr.INPUT_TOKENS) or 0), int(a.get(Attr.OUTPUT_TOKENS) or 0)
    start = int(span.get("startTimeUnixNano") or 0) / 1e9
    end = int(span.get("endTimeUnixNano") or 0) / 1e9
    duration_ms = round((end - start) * 1000, 2) if end else 0.0
    now = time.time() if now is None else now
    skew = 0.0
    if abs(start - now) > MAX_SKEW_S:   # the agent clock is off: use the receive time, keep the duration
        skew = start - now
        dur = (end - start) if end else 0.0
        start = now
        end = now + dur if end else 0.0
    preview = str(a.get(Attr.CS_PROMPT_PREVIEW) or "")[:200]
    status_code = (span.get("status") or {}).get("code", 0)
    tool_args = a.get(Attr.CS_TOOL_ARGS) or "{}"
    return SpanRow(
        agent_id=agent_id, operation=_operation(a, name), name=name,
        trace_id=to_hex(span.get("traceId", "")), span_id=to_hex(span.get("spanId", "")),
        parent_span_id=to_hex(span.get("parentSpanId", "")),
        provider=str(a.get(Attr.PROVIDER) or a.get("gen_ai.system") or ""), model=model,
        input_tokens=tin, output_tokens=tout, cost_usd=cost_usd(model, tin, tout) if (tin or tout) else 0.0,
        tool_name=str(a.get(Attr.TOOL_NAME) or ""),
        tool_args=tool_args if isinstance(tool_args, str) else json.dumps(tool_args),
        prompt_preview=preview, prompt_hash=str(a.get(Attr.CS_PROMPT_HASH) or (prompt_hash(preview) if preview else "")),
        task_id=str(a.get(Attr.CS_TASK_ID) or ""), task_status=str(a.get(Attr.CS_TASK_STATUS) or ""),
        status="error" if status_code in ERROR_CODES else "ok", error_type=str(a.get(Attr.ERROR_TYPE) or ""),
        start_ts=start, end_ts=end, duration_ms=duration_ms,
        detail=_with_skew(_node_detail(a) if _operation(a, name) == "graph_node" else "{}", skew),
    )


def _node_detail(a: dict) -> str:
    """graph_node attributes → the spans.detail JSON column (CONTRACTS §4/§5)."""
    try:
        changed = json.loads(a.get(Attr.CS_NODE_STATE_DELTA) or "{}")
    except (TypeError, ValueError):
        changed = {"value": str(a.get(Attr.CS_NODE_STATE_DELTA))[:60]}
    step = a.get(Attr.CS_NODE_STEP)
    return json.dumps({"node": str(a.get(Attr.CS_NODE) or ""), "step": int(step) if step is not None else None,
                       "framework": str(a.get(Attr.CS_NODE_FRAMEWORK) or ""),
                       "next": str(a.get(Attr.CS_NODE_NEXT) or ""),
                       "changed": changed if isinstance(changed, dict) else {"value": str(changed)[:60]}},
                      ensure_ascii=False)


def normalize_otlp_json(payload: dict, now: float | None = None) -> list[SpanRow]:
    """ExportTraceServiceRequest (JSON form) → list of SpanRow."""
    now = time.time() if now is None else now
    rows: list[SpanRow] = []
    for rs in payload.get("resourceSpans", []):
        resource = attrs_to_dict((rs.get("resource") or {}).get("attributes"))
        for ss in rs.get("scopeSpans", []) + rs.get("instrumentationLibrarySpans", []):
            for span in ss.get("spans", []):
                rows.append(normalize_span(span, resource, now))
    return rows


def normalize_otlp_protobuf(body: bytes, now: float | None = None) -> list[SpanRow]:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    return normalize_otlp_json(MessageToDict(ExportTraceServiceRequest.FromString(body)), now)
