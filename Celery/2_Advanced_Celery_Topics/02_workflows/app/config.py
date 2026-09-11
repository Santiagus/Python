"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration settings."""

    app_name: str = "Financial Document Underwriting Ingestion API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/underwriting_db"
    redis_url: str = "redis://localhost:6380/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5673//"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

