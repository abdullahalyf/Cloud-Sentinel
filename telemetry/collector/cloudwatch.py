"""
Optional CloudWatch export: every stored span also becomes one EMF JSON line.   Owner: Fojle.

    CS_EXPORT_CLOUDWATCH=true  CS_CLOUDWATCH_FILE=data/cloudwatch.jsonl  python -m telemetry.collector

The CloudWatch agent or Fluent Bit ships the file, so no AWS SDK is needed.
Format: CloudWatch Embedded Metric Format (_aws.CloudWatchMetrics).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("telemetry.cloudwatch")

NAMESPACE = "CloudSentinel"
METRICS = [
    {"Name": "cost_usd", "Unit": "None"},
    {"Name": "input_tokens", "Unit": "Count"},
    {"Name": "output_tokens", "Unit": "Count"},
    {"Name": "duration_ms", "Unit": "Milliseconds"},
]


def emf_line(row) -> dict:
    """One span -> one EMF document."""
    return {
        "_aws": {
            "Timestamp": int(float(row.start_ts or 0) * 1000),
            "CloudWatchMetrics": [{"Namespace": NAMESPACE, "Dimensions": [["agent_id"]], "Metrics": METRICS}],
        },
        "agent_id": row.agent_id,
        "cost_usd": float(row.cost_usd or 0),
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
        "duration_ms": float(row.duration_ms or 0),
        "operation": row.operation,
        "model": row.model,
        "trace_id": row.trace_id,
    }


class CloudWatchExporter:
    """write(rows) appends one JSON line per span. Called from the batcher thread, never from a request."""

    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, rows) -> None:
        text = "".join(json.dumps(emf_line(r), ensure_ascii=False) + "\n" for r in rows)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(text)


def from_settings(cfg) -> Optional[CloudWatchExporter]:
    if not cfg.export_cloudwatch:
        return None
    log.info("CloudWatch EMF export ON -> %s", cfg.cloudwatch_file)
    return CloudWatchExporter(cfg.cloudwatch_file)