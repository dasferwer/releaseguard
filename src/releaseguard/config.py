from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://releaseguard:releaseguard@localhost:5432/releaseguard"
    webhook_secret: str = Field(default="change-me-in-production", min_length=16)
    canary_timeout_seconds: int = Field(default=300, ge=30, le=86_400)
    reconcile_interval_seconds: float = Field(default=2, ge=0.2, le=60)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
