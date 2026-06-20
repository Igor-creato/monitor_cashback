import hashlib
import hmac
import json

import httpx
import pytest
from pydantic import SecretStr

from app.clients.cashback_api import (
    CashbackAPIAuthError,
    CashbackAPIBadResponseError,
    CashbackAPIClient,
    CashbackAPINotFoundError,
    CashbackAPIUnavailableError,
)
from app.core.config import Settings

BASE_URL = "https://cashback.example.test"
SITE_ID = "savelloclub.ru"
SECRET = "cashback-api-secret"
NOW = 1_800_000_000


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        cashback_api_base_url=BASE_URL,
        cashback_api_site_id=SITE_ID,
        cashback_api_secret=SecretStr(SECRET),
        cashback_api_timeout_seconds=3.5,
    )


def _signature(timestamp: str, raw_body: bytes) -> str:
    return hmac.new(
        SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()


def _client_for(handler) -> CashbackAPIClient:
    transport = httpx.MockTransport(handler)
    return CashbackAPIClient(
        settings=_settings(),
        transport=transport,
        time_provider=lambda: NOW,
    )


def _json_body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


def test_signature_is_built_from_timestamp_dot_raw_body() -> None:
    seen: dict[str, str] = {}
    payload = {"url": "https://testshop.local/product/123", "price": 1999}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["signature"] = request.headers["X-Savello-Signature"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"status": "resolved"})

    client = _client_for(handler)

    client.resolve_product(payload)

    expected_body = json.dumps(payload, separators=(",", ":"))
    assert seen["body"] == expected_body
    assert seen["signature"] == _signature(str(NOW), expected_body.encode())


def test_hmac_headers_are_added_to_request() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["site"] = request.headers["X-Savello-Site"]
        seen["timestamp"] = request.headers["X-Savello-Timestamp"]
        seen["signature"] = request.headers["X-Savello-Signature"]
        return httpx.Response(200, json={"version": 1})

    client = _client_for(handler)

    client.get_manifest()

    assert seen == {
        "site": SITE_ID,
        "timestamp": str(NOW),
        "signature": _signature(str(NOW), b""),
    }


def test_resolve_product_posts_expected_payload() -> None:
    payload = {"url": "https://testshop.local/product/123", "price": 1999}
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = _json_body(request)
        return httpx.Response(200, json={"merchant_id": "42"})

    client = _client_for(handler)

    response = client.resolve_product(payload)

    assert response == {"merchant_id": "42"}
    assert seen == {
        "method": "POST",
        "path": "/wp-json/savello-internal/v1/resolve-product",
        "payload": payload,
    }


def test_create_deeplink_posts_expected_payload() -> None:
    payload = {"merchant_id": "42", "target_url": "https://shop.example/item"}
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = _json_body(request)
        return httpx.Response(200, json={"deeplink": "https://go.example/click"})

    client = _client_for(handler)

    response = client.create_deeplink(payload)

    assert response == {"deeplink": "https://go.example/click"}
    assert seen == {
        "method": "POST",
        "path": "/wp-json/savello-internal/v1/deeplink",
        "payload": payload,
    }


def test_send_price_monitor_notification_posts_expected_payload() -> None:
    payload = {
        "notification_id": 123,
        "event_type": "target_price_reached",
        "channel": "email",
        "site_id": SITE_ID,
        "external_user_id": "wp:savelloclub.ru:123",
        "dedup_key": "subscription:1:target_price_reached:900.00",
        "template": "price_monitor_target_price_reached",
        "subject_data": {},
        "body_data": {"price": "900.00"},
        "created_at": "2026-06-20T12:00:00Z",
    }
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = _json_body(request)
        seen["signature"] = request.headers["X-Savello-Signature"]
        return httpx.Response(200, json={"status": "queued"})

    client = _client_for(handler)

    response = client.send_price_monitor_notification(payload)

    expected_body = json.dumps(payload, separators=(",", ":"))
    assert response == {"status": "queued"}
    assert seen == {
        "method": "POST",
        "path": "/wp-json/savello-internal/v1/price-monitor/notifications",
        "payload": payload,
        "signature": _signature(str(NOW), expected_body.encode()),
    }


def test_404_maps_to_not_found_error() -> None:
    client = _client_for(lambda request: httpx.Response(404, json={"error": "missing"}))

    with pytest.raises(CashbackAPINotFoundError):
        client.get_merchant_rates("missing")


def test_500_maps_to_unavailable_error() -> None:
    client = _client_for(lambda request: httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(CashbackAPIUnavailableError):
        client.get_manifest()


def test_invalid_json_maps_to_bad_response_error() -> None:
    client = _client_for(lambda request: httpx.Response(200, content=b"not json"))

    with pytest.raises(CashbackAPIBadResponseError):
        client.get_manifest()


def test_secret_is_not_exposed_in_repr_or_exception() -> None:
    client = _client_for(lambda request: httpx.Response(401, json={"error": "auth"}))

    assert SECRET not in repr(client)

    with pytest.raises(CashbackAPIAuthError) as exc_info:
        client.get_manifest()

    assert SECRET not in repr(exc_info.value)
