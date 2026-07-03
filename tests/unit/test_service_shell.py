from price_monitor.core.config import Settings
from price_monitor.core.security import build_signed_headers, verify_signed_request
from price_monitor.workers.celery_app import create_celery_app


def test_live_health_endpoint(client):
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_keep_reusable_infrastructure_only():
    settings = Settings()

    assert settings.app_name == "monitor-cashback-service"
    assert not hasattr(settings, "decodo_web_scraping_api_token")
    assert not hasattr(settings, "joom_browser_provider_url")


def test_hmac_helpers_remain_available_for_future_service_routes():
    body = b'{"ok":true}'
    headers = build_signed_headers(
        secret="secret",
        method="POST",
        path="/api/v1/example",
        body=body,
        request_id="request-1",
        timestamp=1_700_000_000,
    )

    verified = verify_signed_request(
        headers=headers,
        method="POST",
        path="/api/v1/example",
        body=body,
        secrets=["secret"],
        now=1_700_000_001,
    )

    assert verified.request_id == "request-1"


def test_celery_shell_uses_generic_queue_names():
    app = create_celery_app("memory://", "redis://redis:6379/0")

    assert app.conf.task_default_queue == "monitor-cashback.default"
    assert "monitor-cashback.default" in {queue.name for queue in app.conf.task_queues}
