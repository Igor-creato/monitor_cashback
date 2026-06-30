import json
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from tests.conftest import signed_headers

from price_monitor.core.security import build_signed_headers


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
        headers=_signed_query_headers(
            "/api/v1/sources/supported",
            {"url": "https://example.com/p/1"},
            request_id="req-supported",
        ),
    )
    missing = client.get(
        "/api/v1/sources/supported",
        params={"url": "https://unsupported.test/p/1"},
        headers=_signed_query_headers(
            "/api/v1/sources/supported",
            {"url": "https://unsupported.test/p/1"},
            request_id="req-unsupported",
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


def test_supported_source_signature_cannot_be_reused_for_different_url(
    client: TestClient,
) -> None:
    first_source = {
        "source_domain": "example.com",
        "display_name": "Example",
        "logo_url": "https://example.com/logo.png",
        "status": "active",
        "fetch_interval_hours": 6,
        "history_retention_days": 90,
        "browser_fallback_allowed": False,
        "proxy_pool_id": None,
    }
    second_source = {
        "source_domain": "other.com",
        "display_name": "Other",
        "logo_url": "https://other.com/logo.png",
        "status": "active",
        "fetch_interval_hours": 6,
        "history_retention_days": 90,
        "browser_fallback_allowed": False,
        "proxy_pool_id": None,
    }
    for request_id, payload in (
        ("req-admin-source-1", first_source),
        ("req-admin-source-2", second_source),
    ):
        body = json.dumps(payload, separators=(",", ":")).encode()
        response = client.post(
            "/api/v1/admin/sources",
            content=body,
            headers=signed_headers(
                "POST",
                "/api/v1/admin/sources",
                body,
                request_id=request_id,
                idempotency_key=f"idem-{request_id}",
            ),
        )
        assert response.status_code == 201

    reused_signature = client.get(
        "/api/v1/sources/supported",
        params={"url": "https://other.com/p/2"},
        headers=_signed_query_headers(
            "/api/v1/sources/supported",
            {"url": "https://example.com/p/1"},
            request_id="req-supported-replay",
        ),
    )

    assert reused_signature.status_code == 401
    assert reused_signature.json()["error"]["code"] == "authentication_failed"


def test_supported_source_rejects_duplicate_url_query_params(
    client: TestClient,
) -> None:
    supported_source = {
        "source_domain": "example.com",
        "display_name": "Example",
        "logo_url": "https://example.com/logo.png",
        "status": "active",
        "fetch_interval_hours": 6,
        "history_retention_days": 90,
        "browser_fallback_allowed": False,
        "proxy_pool_id": None,
    }
    body = json.dumps(supported_source, separators=(",", ":")).encode()
    create = client.post(
        "/api/v1/admin/sources",
        content=body,
        headers=signed_headers(
            "POST",
            "/api/v1/admin/sources",
            body,
            request_id="req-admin-source-duplicate-url",
            idempotency_key="idem-duplicate-url",
        ),
    )
    assert create.status_code == 201

    signed_query = (
        "url=https%3A%2F%2Fexample.com%2Fp%2F1&url=https%3A%2F%2Funsupported.test%2Fp%2F1"
    )
    replayed_query = (
        "url=https%3A%2F%2Funsupported.test%2Fp%2F1&url=https%3A%2F%2Fexample.com%2Fp%2F1"
    )
    replayed = client.get(
        f"/api/v1/sources/supported?{replayed_query}",
        headers=_signed_raw_query_headers(
            "/api/v1/sources/supported",
            signed_query,
            request_id="req-supported-duplicate-url",
        ),
    )

    assert replayed.status_code == 422


def test_admin_source_contract_rejects_invalid_payloads(client: TestClient) -> None:
    invalid_cases = (
        (
            "invalid-status",
            {
                "source_domain": "example.com",
                "display_name": "Example",
                "logo_url": "https://example.com/logo.png",
                "status": "broken",
                "fetch_interval_hours": 6,
                "history_retention_days": 90,
                "browser_fallback_allowed": False,
                "proxy_pool_id": None,
            },
        ),
        (
            "broad-domain",
            {
                "source_domain": "co.uk",
                "display_name": "Too Broad",
                "logo_url": "https://example.co.uk/logo.png",
                "status": "active",
                "fetch_interval_hours": 6,
                "history_retention_days": 90,
                "browser_fallback_allowed": False,
                "proxy_pool_id": None,
            },
        ),
        (
            "malformed-domain",
            {
                "source_domain": "https://example.com/store",
                "display_name": "Malformed",
                "logo_url": "https://example.com/logo.png",
                "status": "active",
                "fetch_interval_hours": 6,
                "history_retention_days": 90,
                "browser_fallback_allowed": False,
                "proxy_pool_id": None,
            },
        ),
    )

    for request_id, payload in invalid_cases:
        body = json.dumps(payload, separators=(",", ":")).encode()
        response = client.post(
            "/api/v1/admin/sources",
            content=body,
            headers=signed_headers(
                "POST",
                "/api/v1/admin/sources",
                body,
                request_id=f"req-{request_id}",
                idempotency_key=f"idem-{request_id}",
            ),
        )

        assert response.status_code == 422


def _signed_query_headers(
    path: str,
    params: dict[str, str],
    *,
    request_id: str,
) -> dict[str, str]:
    return build_signed_headers(
        secret="test-secret",
        method="GET",
        path=path,
        query=urlencode(params),
        body=b"",
        request_id=request_id,
    )


def _signed_raw_query_headers(
    path: str,
    query: str,
    *,
    request_id: str,
) -> dict[str, str]:
    return build_signed_headers(
        secret="test-secret",
        method="GET",
        path=path,
        query=query,
        body=b"",
        request_id=request_id,
    )
