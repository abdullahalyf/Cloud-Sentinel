"""python -m telemetry.collector   → OTLP/HTTP receiver on :4318 (CS_COLLECTOR_PORT)."""
import logging

import uvicorn

from shared.config import settings
from shared.store import get_store
from telemetry.collector.app import create_app
from telemetry.collector.cloudwatch import from_settings as cloudwatch_from_settings
from telemetry.collector.phoenix import from_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
print(f"CloudSentinel collector on http://0.0.0.0:{settings.collector_port}/v1/traces")
phoenix = from_settings(settings)
if phoenix:
    print(f"  + forwarding to Arize Phoenix at {phoenix.url} (project {phoenix.project})")
cloudwatch = cloudwatch_from_settings(settings)
if cloudwatch:
    print(f"  + writing CloudWatch EMF lines to {cloudwatch.path}")
uvicorn.run(create_app(get_store(), phoenix, cloudwatch=cloudwatch), host="0.0.0.0", port=settings.collector_port, log_level="warning")
