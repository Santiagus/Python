"""Application configuration and environment settings.

Utilizes Pydantic Settings to load, validate, and document runtime configuration
from environment variables, .env files, or default values.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings for the Payment Orchestrator application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Database Connection Strings
    # 1. Database Connection Strings & Pooling
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/payments_db",
        description="Async SQLAlchemy database connection URL (asyncpg driver)",
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/payments_db",
        description="Synchronous database connection URL for Celery workers or migrations",
    )
    db_pool_size: int = Field(
        default=10,
        description="SQLAlchemy async connection pool size for API gateway",
    )
    db_max_overflow: int = Field(
        default=20,
        description="SQLAlchemy max overflow connections for API gateway",
    )
    db_worker_pool_size: int = Field(
        default=2,
        description="SQLAlchemy connection pool size for single-threaded worker child processes",
    )
    db_worker_max_overflow: int = Field(
        default=2,
        description="SQLAlchemy max overflow connections for worker child processes",
    )

    # 2. Broker & Backend Connections
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        description="AMQP 0-9-1 connection URL for RabbitMQ broker",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching, rate limiting, and result backend",
    )

    # 3. External Services & Simulator Endpoints
    bank_api_url: str = Field(
        default="http://localhost:8011",
        description="Base URL for the external partner bank simulator API",
    )

    # 4. Operational & Security Settings
    service_name: str = Field(
        default="api",
        description="Identifies the specific service instance or SLA pool (e.g. api_instant, api_batch)",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment (development, staging, production, test)",
    )
    log_level: str = Field(
        default="INFO",
        description="Application logging verbosity level",
    )
    api_key: str = Field(
        default="sk_live_payment_orchestrator_secret_key_2026",
        description="Master API authentication key for inbound API gateway endpoints",
    )
    rate_limit_rpm: int = Field(
        default=600,
        description="Maximum incoming requests per minute per IP address on public endpoints",
    )

    # 5. Routing & Queue Architecture Constants
    batch_chunk_size: int = Field(
        default=100,
        description="Number of disbursement line items per Celery task chunk",
    )
    critical_queue: str = Field(
        default="critical",
        description="Queue name for real-time, sub-100ms instant payouts (FedNow/RTP)",
    )
    default_queue: str = Field(
        default="default",
        description="Queue name for standard notifications, receipts, and webhooks",
    )
    bulk_queue: str = Field(
        default="bulk",
        description="Queue name for high-volume, batch payroll settlements",
    )
    dlq_queue: str = Field(
        default="rejected_payments",
        description="Dead-letter queue name for unroutable or rejected payments",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
