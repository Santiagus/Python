# =============================================================================
# Autonomous Headless Celery Worker Dockerfile
# Principle of Least Privilege: Zero web server bloat (no uvicorn/fastapi)
# =============================================================================
FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

# Install isolated worker dependencies
COPY services/worker/requirements.txt /workspace/services/worker/requirements.txt
RUN pip install --no-cache-dir -r /workspace/services/worker/requirements.txt

COPY . /workspace/

ENV PYTHONPATH=/workspace
ENV PYTHONUNBUFFERED=1

CMD ["celery", "-A", "services.worker.celery_app.celery_app", "worker", "--loglevel=INFO", "-Q", "card_disputes", "-c", "2"]
