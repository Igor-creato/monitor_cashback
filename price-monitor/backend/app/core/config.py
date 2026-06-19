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
    cashback_api_timeout_seconds: float = 10.0
    price_monitor_incoming_site_id: str = ""
    price_monitor_incoming_secret: SecretStr = SecretStr("")
    admin_api_key: SecretStr = SecretStr("")
    product_image_public_base_url: str = ""
    object_storage_enabled: bool = False
    object_storage_endpoint: str = ""
    object_storage_access_key: SecretStr = SecretStr("")
    object_storage_secret_key: SecretStr = SecretStr("")
    object_storage_bucket: str = ""
    object_storage_public_base_url: str = ""
    browserless_ws_url: str = ""
    browserless_token: SecretStr = SecretStr("")
    marketplace_session_keyring: SecretStr = SecretStr("")
    marketplace_session_active_key_version: str = ""
    marketplace_sync_interval_seconds: int = 3600
    marketplace_sync_due_limit: int = 100
    marketplace_sync_rate_limit_seconds: int = 900
    scheduler_due_fetch_limit: int = 100
    celery_scheduler_interval_seconds: int = 300
    celery_cleanup_interval_seconds: int = 86400
    celery_quarantine_refresh_interval_seconds: int = 600
    celery_marketplace_sync_interval_seconds: int = 300
    cleanup_price_history_retention_days: int = 30
    cleanup_fetch_jobs_retention_days: int = 30
    cleanup_notification_events_retention_days: int = 30

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        extra="ignore",
    )


settings = Settings()
