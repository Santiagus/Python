FROM python:3.11-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/bank_simulator_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/bank_simulator_api/ ./services/bank_simulator_api

EXPOSE 8010

CMD ["uvicorn", "services.bank_simulator_api.main:app", "--host", "0.0.0.0", "--port", "8010"]

