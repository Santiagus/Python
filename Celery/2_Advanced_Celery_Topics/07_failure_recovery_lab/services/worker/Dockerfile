FROM python:3.11-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared
COPY services/worker/ ./services/worker

CMD ["celery", "-A", "services.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "-Q", "wire.settlement.critical", "-c", "2"]

