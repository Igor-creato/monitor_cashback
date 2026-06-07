import hashlib
import hmac

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core import config, incoming_hmac
from app.main import app

SECRET = "incoming-test-secret"
SITE_ID = "savelloclub.test"
NOW = 1_800_000_000


def _signature(timestamp: str, raw_body: bytes, secret: str = SECRET) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()


def _headers(
    timestamp: str,
    raw_body: bytes,
    signature: str | None = None,
) -> dict[str, str]:
    return {
        "X-Savello-Site": SITE_ID,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": signature or _signature(timestamp, raw_body),
    }


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(SECRET),
    )
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW)
    return TestClient(app)


def test_valid_signature_is_accepted(monkeypatch) -> None:
    body = b'{"product_id":"sku-1"}'
    timestamp = str(NOW)
    client = _client(monkeypatch)

    response = client.post(
        "/internal/wordpress/ping",
        content=body,
        headers=_headers(timestamp, body),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_signature_is_rejected(monkeypatch) -> None:
    body = b'{"product_id":"sku-1"}'
    timestamp = str(NOW)
    client = _client(monkeypatch)

    response = client.post(
        "/internal/wordpress/ping",
        content=body,
        headers=_headers(timestamp, body, signature="bad-signature"),
    )

    assert response.status_code == 403


def test_expired_timestamp_is_rejected(monkeypatch) -> None:
    body = b'{"product_id":"sku-1"}'
    timestamp = str(NOW - 301)
    client = _client(monkeypatch)

    response = client.post(
        "/internal/wordpress/ping",
        content=body,
        headers=_headers(timestamp, body),
    )

    assert response.status_code == 403


def test_missing_headers_are_rejected(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post("/internal/wordpress/ping", content=b"{}")

    assert response.status_code == 401


def test_signature_uses_raw_body_not_reencoded_json(monkeypatch) -> None:
    raw_body = b'{"b":2, "a":1}'
    timestamp = str(NOW)
    client = _client(monkeypatch)

    response = client.post(
        "/internal/wordpress/ping",
        content=raw_body,
        headers=_headers(timestamp, raw_body),
    )

    assert response.status_code == 200
