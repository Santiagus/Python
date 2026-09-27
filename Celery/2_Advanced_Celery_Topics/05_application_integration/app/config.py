"""Application configuration and environment settings for Card Dispute & Chargeback Engine.

Utilizes Pydantic Settings to load, validate, and document runtime configuration
from environment variables, .env files, or default values.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings for the Card Dispute & Chargeback Engine."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Database Connection Strings & Role-Budgeted Connection Pooling
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/card_disputes_db",
        description="Async SQLAlchemy database connection URL (asyncpg driver)",
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/card_disputes_db",
        description="Synchronous database connection URL for synchronous scripts or migrations",
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

    # 2. Broker & Result Backend Connections
    celery_broker_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        description="AMQP 0-9-1 connection URL for RabbitMQ broker",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for Celery result backend",
    )

    # 3. Security & Authentication Settings
    api_key_secret: str = Field(
        default="sk_live_card_disputes_test_key_001",
        description="Master API authentication key for inbound API gateway endpoints",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment (development, staging, production, test)",
    )
    log_level: str = Field(
        default="INFO",
        description="Application logging verbosity level",
    )

    # 4. AMQP Topology Constants
    disputes_exchange: str = Field(
        default="disputes.direct",
        description="Primary AMQP direct exchange for card disputes",
    )
    dlx_exchange: str = Field(
        default="disputes.dlx",
        description="Dead-letter AMQP exchange for poisoned or failed dispute tasks",
    )
    disputes_queue: str = Field(
        default="card_disputes",
        description="Primary queue name for card dispute submissions",
    )
    dlq_queue: str = Field(
        default="card_disputes_dlq",
        description="Dead-letter queue name for failed dispute submissions",
    )
    disputes_routing_key: str = Field(
        default="dispute.card.submit",
        description="AMQP routing key for dispute submissions",
    )
    dlq_routing_key: str = Field(
        default="dispute.card.dlq",
        description="AMQP routing key for dead-lettered dispute submissions",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings.

    Returns:
        Settings: Validated global configuration object.
    """
    return Settings()


# Eager Singleton Initialization at Module Load
settings: Settings = get_settings()
