# Image for the simulated AI agents. Built from the REPO ROOT (see docker-compose.yml)
# so it can copy the shared contract file.
FROM python:3.12-slim
WORKDIR /app
COPY shared/__init__.py shared/contracts.py ./shared/
COPY agents/agent.py ./agent.py
# -u = unbuffered output, so every log line reaches the sentinel immediately
CMD ["python", "-u", "agent.py"]
