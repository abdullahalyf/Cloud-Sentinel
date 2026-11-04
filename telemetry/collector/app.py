"""
OTLP/HTTP collector: POST /v1/traces (protobuf or JSON) → normalized SpanRows → store.   Owner: Fojle.
Point ANY OpenTelemetry-instrumented agent here with OTEL_EXPORTER_OTLP_ENDPOINT=http://<host>:4318
"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException, Request, Response

from telemetry.collector.normalize import normalize_otlp_json, normalize_otlp_protobuf

log = logging.getLogger("telemetry.collector")


def create_app(store) -> FastAPI:
    app = FastAPI(title="CloudSentinel OTLP collector")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/v1/traces")
    async def traces(request: Request) -> Response:
        body = await request.body()
        ctype = request.headers.get("content-type", "")
        try:
            rows = normalize_otlp_json(json.loads(body or b"{}")) if "json" in ctype else normalize_otlp_protobuf(body)
        except Exception as exc:
            raise HTTPException(400, f"cannot parse OTLP payload: {exc}")
        store.insert_spans(rows)
        if rows:
            log.info("stored %d spans from %s", len(rows), ", ".join(sorted({r.agent_id for r in rows})))
        if "json" in ctype:
            return Response(content="{}", media_type="application/json")
        return Response(content=b"", media_type="application/x-protobuf")  # empty ExportTraceServiceResponse

    return app
