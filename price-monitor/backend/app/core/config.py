from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "price-monitor-api"
    app_env: str = ""
    database_url: str = ""
    redis_url: str = ""
    rabbitmq_url: str = ""
    cashback_api_base_url: str = ""
    cashback_api_site_id: str = ""
    cashback_api_secret: SecretStr = SecretStr("")
    price_monitor_incoming_site_id: str = ""
    price_monitor_incoming_secret: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        extra="ignore",
    )


settings = Settings()
