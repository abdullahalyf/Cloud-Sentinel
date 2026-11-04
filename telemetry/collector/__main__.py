"""python -m telemetry.collector   → OTLP/HTTP receiver on :4318 (CS_COLLECTOR_PORT)."""
import logging

import uvicorn

from shared.config import settings
from shared.store import get_store
from telemetry.collector.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
print(f"CloudSentinel collector on http://0.0.0.0:{settings.collector_port}/v1/traces")
uvicorn.run(create_app(get_store()), host="0.0.0.0", port=settings.collector_port, log_level="warning")
