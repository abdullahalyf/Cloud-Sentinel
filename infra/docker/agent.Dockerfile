# Simulated agent image (SDK + simulator only, no repo code). Built from the REPO ROOT.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "opentelemetry-sdk>=1.30" "opentelemetry-exporter-otlp-proto-http>=1.30"
COPY telemetry/sdk/cloudsentinel ./sdk/cloudsentinel
COPY telemetry/simulators/agent.py ./simulators/agent.py
# -u = unbuffered output so `docker logs` is live
CMD ["python", "-u", "simulators/agent.py"]
