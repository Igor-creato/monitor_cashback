import json

from fastapi.testclient import TestClient
from tests.conftest import signed_headers


def test_admin_source_and_settings_contract(client: TestClient) -> None:
    create_path = "/api/v1/admin/sources"
    create_body = {
        "source_domain": "example.com",
        "display_name": "Example",
        "logo_url": "https://example.com/logo.png",
        "status": "active",
        "fetch_interval_hours": 6,
        "history_retention_days": 90,
        "browser_fallback_allowed": False,
        "proxy_pool_id": None,
    }
    create_raw = json.dumps(create_body, separators=(",", ":")).encode()

    create = client.post(
        create_path,
        content=create_raw,
        headers=signed_headers(
            "POST", create_path, create_raw, request_id="req-admin-source", idempotency_key="idem-1"
        ),
    )
    listed = client.get(
        create_path,
        headers=signed_headers(
            "GET", create_path, b"", request_id="req-list", idempotency_key=None
        ),
    )
    supported = client.get(
        "/api/v1/sources/supported",
        params={"url": "https://example.com/p/1"},
        headers=signed_headers(
            "GET",
            "/api/v1/sources/supported",
            b"",
            request_id="req-supported",
            idempotency_key=None,
        ),
    )
    missing = client.get(
        "/api/v1/sources/supported",
        params={"url": "https://unsupported.test/p/1"},
        headers=signed_headers(
            "GET",
            "/api/v1/sources/supported",
            b"",
            request_id="req-unsupported",
            idempotency_key=None,
        ),
    )

    settings_path = "/api/v1/admin/settings"
    settings_body = {"max_tracked_products_per_user": 25}
    settings_raw = json.dumps(settings_body, separators=(",", ":")).encode()
    update_settings = client.patch(
        settings_path,
        content=settings_raw,
        headers=signed_headers(
            "PATCH",
            settings_path,
            settings_raw,
            request_id="req-settings-update",
            idempotency_key="idem-2",
        ),
    )
    get_settings = client.get(
        settings_path,
        headers=signed_headers(
            "GET", settings_path, b"", request_id="req-settings-get", idempotency_key=None
        ),
    )

    assert create.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["sources"][0]["source_domain"] == "example.com"
    assert supported.status_code == 200
    assert supported.json()["supported"] is True
    assert supported.json()["source"]["source_domain"] == "example.com"
    assert missing.status_code == 200
    assert missing.json() == {
        "supported": False,
        "error": {"code": "unsupported_store", "message": "Магазин не поддерживается"},
    }
    assert update_settings.status_code == 200
    assert update_settings.json()["settings"]["max_tracked_products_per_user"] == 25
    assert get_settings.status_code == 200
    assert get_settings.json()["settings"]["max_tracked_products_per_user"] == 25
