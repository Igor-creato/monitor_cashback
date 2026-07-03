from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the reusable backend service shell."""

    model_config = SettingsConfigDict(env_prefix="PRICE_MONITOR_", env_file=".env", extra="ignore")

    app_name: str = "monitor-cashback-service"
    environment: str = "development"
    external_base_url: str = "http://localhost:8000"
    database_url: str = (
        "postgresql+psycopg://price_monitor:price_monitor@postgres:5432/price_monitor"
    )
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://price_monitor:price_monitor@rabbitmq:5672//"
    hmac_secrets: str = Field(default="", description="Comma-separated HMAC shared secrets.")
    hmac_replay_window_seconds: int = 300
    db_pool_recycle_seconds: int = 3600

    @property
    def hmac_secret_list(self) -> list[str]:
        return [secret.strip() for secret in self.hmac_secrets.split(",") if secret.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
