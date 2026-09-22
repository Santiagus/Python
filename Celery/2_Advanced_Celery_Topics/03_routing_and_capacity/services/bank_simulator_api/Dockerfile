# =============================================================================
# Standalone Partner Bank Simulator API Dockerfile
# Principle of Least Privilege: Lean image (~80MB), no Celery or DB drivers
# =============================================================================

FROM python:3.11-slim

WORKDIR /workspace

# Install minimal curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/bank_simulator_api/requirements.txt /workspace/services/bank_simulator_api/requirements.txt
RUN pip install --no-cache-dir -r /workspace/services/bank_simulator_api/requirements.txt

COPY services/bank_simulator_api/ /workspace/services/bank_simulator_api/

ENV PYTHONPATH=/workspace
ENV PYTHONUNBUFFERED=1

EXPOSE 8011

CMD ["uvicorn", "services.bank_simulator_api.main:app", "--host", "0.0.0.0", "--port", "8011"]

