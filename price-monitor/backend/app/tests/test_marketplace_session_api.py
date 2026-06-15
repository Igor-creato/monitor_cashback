from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config
from app.main import app
from app.models.monitoring import (
    MarketplaceConnection,
    MarketplaceSessionAllowlist,
    MarketplaceSessionAuditEvent,
    MarketplaceSessionSecret,
    MarketplaceSessionSource,
)
from app.services.marketplace_sessions import decrypt_session_bundle_for_sync

SITE_ID = "savelloclub.ru"
INCOMING_SECRET = "incoming-secret"
ADMIN_KEY = "admin-test-key"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> Iterator[TestClient]:
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(INCOMING_SECRET),
    )
    monkeypatch.setattr(config.settings, "admin_api_key", SecretStr(ADMIN_KEY))
    monkeypatch.setattr(
        config.settings,
        "marketplace_session_keyring",
        SecretStr("v1:" + base64.b64encode(b"k" * 32).decode()),
    )
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    monkeypatch.setattr(
        "app.core.incoming_hmac.current_unix_time",
        lambda: 1_781_516_800,
    )
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _signed_headers(raw_body: bytes = b"") -> dict[str, str]:
    timestamp = "1781516800"
    signature = hmac.new(
        INCOMING_SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Savello-Site": SITE_ID,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": signature,
        "Content-Type": "application/json",
    }


def _admin_headers() -> dict[str, str]:
    return {"ADMIN_API_KEY": ADMIN_KEY}


def _enable_marketplace(
    session: Session,
    *,
    marketplace: str = "ozon",
    source_enabled: bool = True,
    allowlist_enabled: bool = True,
) -> None:
    session.add(
        MarketplaceSessionSource(
            marketplace=marketplace,
            enabled=source_enabled,
            disabled_reason=None if source_enabled else "security_hold",
        )
    )
    session.add_all(
        [
            MarketplaceSessionAllowlist(
                marketplace=marketplace,
                name="session-id",
                kind="cookie",
                scope="cart_read",
                purpose="cart_sync",
                enabled=allowlist_enabled,
            ),
            MarketplaceSessionAllowlist(
                marketplace=marketplace,
                name="x-token",
                kind="token",
                scope="favorites_read",
                purpose="favorites_sync",
                enabled=allowlist_enabled,
            ),
        ]
    )
    session.commit()


def _connect_payload(
    *,
    external_user_id: str = "wp:savelloclub.ru:123",
    marketplace: str = "ozon",
) -> dict:
    return {
        "site_id": SITE_ID,
        "external_user_id": external_user_id,
        "marketplace": marketplace,
        "consent_version": "price-assistant-session-v1",
        "scope": ["cart_read", "favorites_read"],
        "captured_at": "2026-06-15T10:00:00Z",
        "connector_version": "0.1.0",
        "session_bundle": {
            "cookies": [
                {
                    "name": "session-id",
                    "value": "secret-cookie",
                    "domain": ".ozon.ru",
                    "path": "/",
                    "expires": "2026-06-16T10:00:00Z",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ],
            "tokens": [
                {
                    "name": "x-token",
                    "value": "secret-token",
                    "expires": "2026-06-16T10:00:00Z",
                }
            ],
            "captured_at": "2026-06-15T10:00:00Z",
            "user_agent_hint": "desktop-chromium",
            "region_hint": "msk",
        },
    }


def _post_signed(client: TestClient, payload: dict):
    raw = json.dumps(payload, separators=(",", ":"))
    return client.post(
        "/v1/marketplace-connections",
        content=raw,
        headers=_signed_headers(raw.encode()),
    )


def test_connect_stores_encrypted_bundle_and_returns_no_secrets(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session)
    payload = _connect_payload()

    response = _post_signed(client, payload)

    assert response.status_code == 200
    assert response.json() == {
        "connection_id": 1,
        "marketplace": "ozon",
        "status": "connected",
        "last_validated_at": None,
        "last_synced_at": None,
        "next_retry_at": None,
        "reason": None,
    }
    assert "secret-cookie" not in response.text
    assert "secret-token" not in response.text
    assert "encrypted_cookie_bundle" not in response.text

    secret = db_session.scalar(select(MarketplaceSessionSecret))
    assert secret is not None
    assert "secret-cookie" not in secret.encrypted_cookie_bundle
    assert "secret-token" not in secret.encrypted_cookie_bundle
    assert secret.key_version == "v1"


def test_connect_rejects_password_and_filters_non_allowlisted_values(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session)
    password_payload = _connect_payload()
    password_payload["session_bundle"]["password"] = "marketplace-password"
    mixed_payload = _connect_payload()
    mixed_payload["session_bundle"]["cookies"].append(
        {
            "name": "not-allowed",
            "value": "drop-me",
            "domain": ".ozon.ru",
            "path": "/",
            "expires": None,
            "secure": True,
            "httpOnly": False,
            "sameSite": "Lax",
        }
    )
    empty_after_filter_payload = _connect_payload()
    empty_after_filter_payload["session_bundle"]["cookies"][0]["name"] = "not-allowed"
    empty_after_filter_payload["session_bundle"]["tokens"][0]["name"] = "also-denied"

    password_response = _post_signed(client, password_payload)
    mixed_response = _post_signed(client, mixed_payload)
    empty_after_filter_response = _post_signed(client, empty_after_filter_payload)

    assert password_response.status_code == 422
    assert password_response.json()["detail"] == "prohibited_session_field"
    assert mixed_response.status_code == 200
    connection = db_session.get(
        MarketplaceConnection, mixed_response.json()["connection_id"]
    )
    assert connection is not None
    decrypted = decrypt_session_bundle_for_sync(
        db_session,
        connection.id,
        worker_name="test-worker",
    )
    assert [cookie["name"] for cookie in decrypted["cookies"]] == ["session-id"]
    assert "drop-me" not in json.dumps(decrypted)
    assert empty_after_filter_response.status_code == 422
    assert (
        empty_after_filter_response.json()["detail"]
        == "session_bundle_contains_no_allowlisted_values"
    )


def test_connect_rejects_disabled_marketplace_and_empty_allowlist(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session, marketplace="ozon", source_enabled=False)
    db_session.add(MarketplaceSessionSource(marketplace="wildberries", enabled=True))
    db_session.commit()

    disabled_response = _post_signed(client, _connect_payload(marketplace="ozon"))
    empty_allowlist_response = _post_signed(
        client,
        _connect_payload(marketplace="wildberries"),
    )

    assert disabled_response.status_code == 423
    assert disabled_response.json()["detail"] == "marketplace_disabled"
    assert empty_allowlist_response.status_code == 422
    assert empty_allowlist_response.json()["detail"] == "session_allowlist_empty"

    audit = db_session.scalar(select(MarketplaceSessionAuditEvent))
    assert audit is not None
    assert audit.event_type == "kill_switch_blocked"
    assert audit.actor_type == "user"


def test_list_connections_is_scoped_and_contains_no_secret_material(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session)
    _post_signed(client, _connect_payload(external_user_id="wp:savelloclub.ru:123"))
    _post_signed(client, _connect_payload(external_user_id="wp:savelloclub.ru:456"))

    response = client.get(
        "/v1/marketplace-connections",
        params={"site_id": SITE_ID, "external_user_id": "wp:savelloclub.ru:123"},
        headers=_signed_headers(),
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "connection_id": 1,
            "marketplace": "ozon",
            "status": "connected",
            "last_validated_at": None,
            "last_synced_at": None,
            "next_retry_at": None,
            "reason": None,
        }
    ]
    assert "secret-cookie" not in response.text
    assert "encrypted_cookie_bundle" not in response.text


def test_disconnect_is_owner_scoped_deletes_secret_access_and_audits(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session)
    _post_signed(client, _connect_payload(external_user_id="wp:savelloclub.ru:123"))

    wrong_owner = client.delete(
        "/v1/marketplace-connections/1",
        params={"site_id": SITE_ID, "external_user_id": "wp:savelloclub.ru:456"},
        headers=_signed_headers(),
    )
    owner = client.delete(
        "/v1/marketplace-connections/1",
        params={"site_id": SITE_ID, "external_user_id": "wp:savelloclub.ru:123"},
        headers=_signed_headers(),
    )

    assert wrong_owner.status_code == 404
    assert owner.status_code == 200
    assert owner.json()["status"] == "disconnected"
    connection = db_session.get(MarketplaceConnection, 1)
    secret = db_session.scalar(select(MarketplaceSessionSecret))
    assert connection is not None
    assert connection.status == "disconnected"
    assert secret is not None
    assert secret.deleted_at is not None
    audit_events = [
        event.event_type
        for event in db_session.scalars(
            select(MarketplaceSessionAuditEvent).order_by(
                MarketplaceSessionAuditEvent.id.asc()
            )
        )
    ]
    assert audit_events == ["connect", "disconnect", "delete"]


def test_admin_marketplace_connections_never_expose_secret_material(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session)
    _post_signed(client, _connect_payload())

    response = client.get(
        "/admin/marketplace-connections",
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    body = response.text
    assert "secret-cookie" not in body
    assert "secret-token" not in body
    assert "encrypted_cookie_bundle" not in body
    assert "dek_ciphertext" not in body
    assert response.json()["items"][0]["key_version"] == "v1"
    assert response.json()["items"][0]["has_secret"] is True
