from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "price-monitor-api"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PRICE_MONITOR_",
    )


settings = Settings()
