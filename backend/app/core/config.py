"""Application settings, loaded once from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- app ---
    app_env: Literal["local", "test", "prod"] = "local"
    log_level: str = "INFO"
    api_port: int = 8000

    # --- security ---
    # HS256 wants at least 32 bytes of key material (RFC 7518 3.2).
    secret_key: str = Field(min_length=32)
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 14

    # --- database ---
    postgres_user: str = "trader"
    postgres_password: str = "trader"  # noqa: S105  local compose default, overridden by .env
    postgres_db: str = "trading"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- redis ---
    redis_host: str = "redis"
    redis_port: int = 6379

    # --- alpaca paper (phase 10) ---
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    # --- notifications (phase 07) ---
    # Blank means notifications are recorded but never pushed.
    telegram_bot_token: str = ""

    # --- reasoning layer (phase 08) ---
    # Off by default: the agent must work without a model, and the model is an
    # optional reviewer rather than a dependency.
    llm_enabled: bool = False
    llm_base_url: str = "http://host.docker.internal:11434"
    llm_model: str = "llama3.2:1b"

    # --- execution ---
    broker: Literal["sim", "alpaca_paper"] = "sim"
    allow_live_trading: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
