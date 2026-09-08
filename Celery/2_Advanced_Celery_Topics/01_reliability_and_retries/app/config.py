from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transaction API"
    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://celery:celery-dev-password@localhost:5432/transactions"
    )
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
