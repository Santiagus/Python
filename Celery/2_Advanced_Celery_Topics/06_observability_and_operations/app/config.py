"""Application configuration and environment settings.

Provides centralized typed settings using Pydantic Settings v2.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration settings for the Fraud & AML Screening Gateway."""

    database_url: str = (
        "postgresql+asyncpg://fraud_user:fraud_pass@localhost:5438/fraud_screening_db"
    )
    redis_url: str = "redis://localhost:6385/0"
    celery_broker_url: str = "amqp://guest:guest@localhost:5678//"
    celery_result_backend: str = "redis://localhost:6385/1"
    sanctions_api_url: str = "http://localhost:8015"
    log_level: str = "INFO"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
