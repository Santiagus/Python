"""Application configuration and environment settings for the transaction API."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration used by the API and worker services."""

    app_name: str = "Transaction API"
    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://celery:celery-dev-password@localhost:5432/transactions"
    )
    log_level: str = "INFO"
    log_format: str = "json"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
