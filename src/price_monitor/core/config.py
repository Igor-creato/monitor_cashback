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
    decodo_scraper_api_url: str = "https://scraper-api.decodo.com/v2/scrape"
    decodo_basic_auth_token: str = Field(
        default="",
        description="Decodo Web Scraping API Basic auth token without the 'Basic ' prefix.",
    )
    decodo_default_headless: str = "html"
    decodo_default_proxy_pool: str = "premium"
    decodo_default_device_type: str = "desktop"
    decodo_request_timeout_seconds: int = 150
    nodemaven_proxy_url: str = Field(
        default="",
        description="Full NodeMaven proxy URL; preferred when copied from Proxy Setup.",
    )
    nodemaven_proxy_host: str = "gate.nodemaven.com"
    nodemaven_proxy_port: int = 8080
    nodemaven_proxy_username: str = ""
    nodemaven_proxy_password: str = ""
    nodemaven_request_timeout_seconds: int = 60
    nodemaven_verify_ssl: bool = True

    @property
    def hmac_secret_list(self) -> list[str]:
        return [secret.strip() for secret in self.hmac_secrets.split(",") if secret.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
