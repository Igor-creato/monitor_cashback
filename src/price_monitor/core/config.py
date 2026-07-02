from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the service.

    Secrets intentionally have no production-grade defaults. Local compose and
    tests pass synthetic values explicitly.
    """

    model_config = SettingsConfigDict(env_prefix="PRICE_MONITOR_", env_file=".env", extra="ignore")

    app_name: str = "price-monitor"
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
    joom_browser_provider_url: str = ""
    joom_browser_provider_token: str = Field(
        default="", description="Bearer token for an approved Joom rendered HTML provider."
    )
    joom_browser_provider_timeout_seconds: float = 25.0
    joom_browser_provider_wait_selector: str = 'meta[property="product:price:amount"]'
    decodo_web_scraping_api_url: str = "https://scraper-api.decodo.com/v2/scrape"
    decodo_web_scraping_api_token: str = Field(
        default="",
        description="Basic auth token for Decodo Web Scraping API, stored only in env.",
    )
    decodo_web_scraping_username: str = Field(
        default="",
        description="Decodo username fallback when token auth is not used.",
    )
    decodo_web_scraping_password: str = Field(
        default="",
        description="Decodo password fallback when token auth is not used.",
    )
    decodo_web_scraping_timeout_seconds: float = 25.0
    decodo_web_scraping_proxy_pool: str = "premium"
    decodo_web_scraping_headless: str = "html"
    decodo_web_scraping_geo: str = ""

    @property
    def hmac_secret_list(self) -> list[str]:
        return [secret.strip() for secret in self.hmac_secrets.split(",") if secret.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
