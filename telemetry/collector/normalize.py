"""
OTLP → SpanRow (CONTRACTS §4). Works on the OTLP *JSON* shape (camelCase keys), which is also what
google.protobuf.json_format.MessageToDict() produces from the protobuf the standard exporter sends.
Pure functions, no network → easy to test.   Owner: Fojle.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from shared.contracts import Attr, SpanRow, prompt_hash
from shared.pricing import cost_usd

ERROR_CODES = (2, "2", "STATUS_CODE_ERROR")


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


def normalize_span(span: dict, resource: dict[str, Any]) -> SpanRow:
    a = attrs_to_dict(span.get("attributes"))
    name = span.get("name", "")
    agent_id = str(a.get(Attr.CS_AGENT_ID) or resource.get(Attr.CS_AGENT_ID) or a.get(Attr.AGENT_ID)
                   or resource.get(Attr.SERVICE_NAME) or "unknown")
    model = str(a.get(Attr.REQUEST_MODEL) or a.get("gen_ai.response.model") or "")
    tin, tout = int(a.get(Attr.INPUT_TOKENS) or 0), int(a.get(Attr.OUTPUT_TOKENS) or 0)
    start = int(span.get("startTimeUnixNano") or 0) / 1e9
    end = int(span.get("endTimeUnixNano") or 0) / 1e9
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
        start_ts=start, end_ts=end, duration_ms=round((end - start) * 1000, 2) if end else 0.0,
    )


def normalize_otlp_json(payload: dict) -> list[SpanRow]:
    """ExportTraceServiceRequest (JSON form) → list of SpanRow."""
    rows: list[SpanRow] = []
    for rs in payload.get("resourceSpans", []):
        resource = attrs_to_dict((rs.get("resource") or {}).get("attributes"))
        for ss in rs.get("scopeSpans", []) + rs.get("instrumentationLibrarySpans", []):
            for span in ss.get("spans", []):
                rows.append(normalize_span(span, resource))
    return rows


def normalize_otlp_protobuf(body: bytes) -> list[SpanRow]:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    return normalize_otlp_json(MessageToDict(ExportTraceServiceRequest.FromString(body)))
