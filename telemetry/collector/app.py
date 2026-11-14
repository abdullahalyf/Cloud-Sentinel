"""
OTLP/HTTP collector: POST /v1/traces (protobuf or JSON) → normalized SpanRows → store.   Owner: Fojle.
Point ANY OpenTelemetry-instrumented agent here with OTEL_EXPORTER_OTLP_ENDPOINT=http://<host>:4318
"""
from __future__ import annotations

import json
import logging
import queue

from fastapi import FastAPI, HTTPException, Request, Response

from telemetry.collector.batcher import SpanBatcher
from telemetry.collector.normalize import normalize_otlp_json, normalize_otlp_protobuf

log = logging.getLogger("telemetry.collector")


def create_app(store, phoenix=None, batcher=None) -> FastAPI:
    """phoenix: optional telemetry.collector.phoenix.PhoenixExporter (CS_EXPORT_PHOENIX=true)."""
    app = FastAPI(title="CloudSentinel OTLP collector")
    batcher = batcher or SpanBatcher(store)
    app.state.batcher = batcher
    app.state.flush = batcher.flush

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
        try:
            batcher.put(rows)
        except queue.Full:
            raise HTTPException(503, "collector queue is full", headers={"Retry-After": "1"})
        if phoenix is not None and rows:
            phoenix.submit(body, ctype)   # background, never blocks or fails the agent
        if "json" in ctype:
            return Response(content="{}", media_type="application/json")
        return Response(content=b"", media_type="application/x-protobuf")  # empty ExportTraceServiceResponse

    return app
