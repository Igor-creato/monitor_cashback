from app.core.config import Settings


def test_settings_loads_required_environment_urls(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://cashback:password@mariadb:3306/cashback",
    )
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    monkeypatch.setenv("CASHBACK_API_BASE_URL", "https://cashback.example.test")
    monkeypatch.setenv("CASHBACK_API_SITE_ID", "local-site")
    monkeypatch.setenv("CASHBACK_API_SECRET", "super-secret-value")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret-value")

    settings = Settings(_env_file=None)

    assert (
        settings.database_url
        == "mysql+pymysql://cashback:password@mariadb:3306/cashback"
    )
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.rabbitmq_url == "amqp://guest:guest@rabbitmq:5672/"
    assert settings.cashback_api_base_url == "https://cashback.example.test"
    assert settings.cashback_api_site_id == "local-site"
    assert settings.admin_api_key.get_secret_value() == "admin-secret-value"


def test_settings_does_not_expose_cashback_api_secret(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://cashback:password@mariadb:3306/cashback",
    )
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    monkeypatch.setenv("CASHBACK_API_BASE_URL", "https://cashback.example.test")
    monkeypatch.setenv("CASHBACK_API_SITE_ID", "local-site")
    monkeypatch.setenv("CASHBACK_API_SECRET", "super-secret-value")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret-value")

    settings = Settings(_env_file=None)

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in repr(settings.model_dump())
    assert "admin-secret-value" not in repr(settings)
    assert "admin-secret-value" not in repr(settings.model_dump())


def test_settings_does_not_expose_object_storage_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "object-access-secret")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "object-secret-secret")

    settings = Settings(_env_file=None)

    assert "object-access-secret" not in repr(settings)
    assert "object-access-secret" not in repr(settings.model_dump())
    assert "object-secret-secret" not in repr(settings)
    assert "object-secret-secret" not in repr(settings.model_dump())


def test_settings_loads_object_storage_environment(monkeypatch) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_ENABLED", "true")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "minioadmin123")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "product-images")
    monkeypatch.setenv(
        "OBJECT_STORAGE_PUBLIC_BASE_URL",
        "http://localhost:9000/product-images",
    )

    settings = Settings(_env_file=None)

    assert settings.object_storage_enabled is True
    assert settings.object_storage_endpoint == "http://minio:9000"
    assert settings.object_storage_access_key.get_secret_value() == "minioadmin"
    assert settings.object_storage_secret_key.get_secret_value() == "minioadmin123"
    assert settings.object_storage_bucket == "product-images"
    assert (
        settings.object_storage_public_base_url
        == "http://localhost:9000/product-images"
    )
