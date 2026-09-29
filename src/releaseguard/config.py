from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APIClient(BaseModel):
    key: SecretStr
    role: Literal["admin", "approver", "observer", "viewer"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://releaseguard:releaseguard@localhost:5432/releaseguard"
    webhook_secret: str = Field(default="change-me-in-production", min_length=16)
    canary_timeout_seconds: int = Field(default=300, ge=30, le=86_400)
    reconcile_interval_seconds: float = Field(default=2, ge=0.2, le=60)
    log_level: str = "INFO"
    api_clients: dict[str, APIClient] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_clients(self) -> "Settings":
        keys = [client.key.get_secret_value() for client in self.api_clients.values()]
        if any(not 1 <= len(name) <= 160 for name in self.api_clients):
            raise ValueError("Имя клиента должно содержать от 1 до 160 символов")
        if any(len(key) < 16 for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("Ключи клиентов должны быть уникальными и не короче 16 символов")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
