# =============================================================================
# Autonomous Headless Celery Worker Dockerfile
# Principle of Least Privilege: Zero web server bloat (no uvicorn/fastapi)
# =============================================================================

FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install isolated worker dependencies
COPY services/worker/requirements.txt /workspace/services/worker/requirements.txt
RUN pip install --no-cache-dir -r /workspace/services/worker/requirements.txt

COPY app/ /workspace/app/
COPY services/__init__.py /workspace/services/__init__.py
COPY services/worker/ /workspace/services/worker/
COPY services/bank_simulator_api/client.py /workspace/services/bank_simulator_api/client.py
COPY services/bank_simulator_api/__init__.py /workspace/services/bank_simulator_api/__init__.py

ENV PYTHONPATH=/workspace
ENV PYTHONUNBUFFERED=1

# Default command (overridden per worker role in docker-compose)
CMD ["celery", "-A", "services.worker.celery_app.celery_app", "worker", "--loglevel=INFO"]

