FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python runtime dependencies
COPY requirements.txt /workspace/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ /workspace/app/
COPY services/ /workspace/services/

# Run as non-root user for container security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /workspace
USER appuser

# Launch Celery worker with concurrency pool
CMD ["celery", "-A", "services.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "-c", "4"]

