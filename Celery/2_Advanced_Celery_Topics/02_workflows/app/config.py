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
    log_level: str = "INFO"
    log_format: str | None = None

    @property
    def effective_log_format(self) -> str:
        """Return 'pretty' for development and 'json' for production by default."""
        if self.log_format:
            return self.log_format
        return "pretty" if self.environment.lower() == "development" else "json"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
