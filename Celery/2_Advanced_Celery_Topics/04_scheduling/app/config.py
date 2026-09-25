"""Application configuration and environment settings for Module 04 Scheduling.

Utilizes Pydantic Settings to load, validate, and document runtime configuration
from environment variables, .env files, or default values.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings for EOD Banking Cut-Off & Ledger Reconciliation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Environment & Logging
    environment: str = Field(
        default="development",
        description="Application environment: development, testing, or production",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging verbosity level",
    )

    # 2. Database Connection Strings & Pooling
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/scheduling_db",
        description="Async SQLAlchemy database connection URL (asyncpg driver)",
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/scheduling_db",
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

    # 3. Message Broker & Result Backend
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        description="AMQP 0-9-1 connection URL for RabbitMQ broker",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for locks and result backend",
    )
    redis_maint_notifications: bool = Field(
        default=False,
        description="Enable Redis CLIENT MAINT_NOTIFICATIONS for cloud-managed Redis (Azure/AWS)",
    )

    # 4. Scheduling & Timezone Constants
    celery_timezone: str = Field(
        default="America/New_York",
        description="Timezone for Celery Beat schedule evaluation (e.g. America/New_York)",
    )
    idempotency_retention_days: int = Field(
        default=30,
        description="Retention threshold in days for purging expired idempotency records",
    )
    leader_lease_ttl_seconds: int = Field(
        default=15,
        description="Redis lease TTL in seconds for Celery Beat leader election",
    )
    leader_heartbeat_interval_seconds: int = Field(
        default=5,
        description="Heartbeat renewal interval in seconds for the active Beat leader",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached singleton application settings.

    Returns:
        Settings: Validated configuration settings instance.
    """
    return Settings()
