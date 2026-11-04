# One image for brain, collector and dashboard (different commands). Built from the REPO ROOT.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "brain"]
