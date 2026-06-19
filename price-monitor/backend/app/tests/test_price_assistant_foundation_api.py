from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal

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
    ImportedCollection,
    ImportedItem,
    MarketplaceConnection,
    MarketplaceSessionAllowlist,
    MarketplaceSessionSecret,
    MarketplaceSessionSource,
    ProductMatchGroup,
    ProductOffer,
    Store,
    TrackedProduct,
    UserProductSubscription,
)

SITE_ID = "savelloclub.ru"
USER_ID = "wp:savelloclub.ru:123"
OTHER_USER_ID = "wp:savelloclub.ru:456"
INCOMING_SECRET = "incoming-secret"
NOW = 1_781_516_800


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
    monkeypatch.setattr(
        config.settings,
        "marketplace_session_keyring",
        SecretStr("v1:" + base64.b64encode(b"k" * 32).decode()),
    )
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    monkeypatch.setattr(
        "app.core.incoming_hmac.current_unix_time",
        lambda: NOW,
    )
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _signed_headers(
    raw_body: bytes = b"",
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    timestamp = str(NOW)
    signature = hmac.new(
        INCOMING_SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-Savello-Site": SITE_ID,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": signature,
        "Content-Type": "application/json",
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _post_json(
    client: TestClient,
    url: str,
    payload: dict,
    *,
    idempotency_key: str | None = "idem-1",
):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return client.post(
        url,
        content=raw,
        headers=_signed_headers(raw, idempotency_key=idempotency_key),
    )


def _enable_marketplace(session: Session, marketplace: str = "ozon") -> None:
    session.add(MarketplaceSessionSource(marketplace=marketplace, enabled=True))
    session.add_all(
        [
            MarketplaceSessionAllowlist(
                marketplace=marketplace,
                name="session-id",
                kind="cookie",
                scope="cart_read",
                purpose="cart_sync",
                enabled=True,
            ),
            MarketplaceSessionAllowlist(
                marketplace=marketplace,
                name="x-token",
                kind="token",
                scope="favorites_read",
                purpose="favorites_sync",
                enabled=True,
            ),
        ]
    )
    session.commit()


def _create_connection_payload(
    *,
    external_user_id: str = USER_ID,
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
    }


def _bundle_payload(external_user_id: str = USER_ID) -> dict:
    payload = _create_connection_payload(external_user_id=external_user_id)
    payload.pop("marketplace")
    payload["session_bundle"] = {
        "cookies": [{"name": "session-id", "value": "secret-cookie"}],
        "tokens": [{"name": "x-token", "value": "secret-token"}],
        "metadata": {"region": "msk"},
    }
    return payload


def _create_connected_marketplace(
    client: TestClient,
    db_session: Session,
    *,
    external_user_id: str = USER_ID,
) -> int:
    _enable_marketplace(db_session)
    create_response = _post_json(
        client,
        "/v1/marketplace-connections",
        _create_connection_payload(external_user_id=external_user_id),
        idempotency_key=None,
    )
    assert create_response.status_code == 200
    connection_id = create_response.json()["connection_id"]
    bundle_response = _post_json(
        client,
        f"/v1/marketplace-connections/{connection_id}/session-bundle",
        _bundle_payload(external_user_id=external_user_id),
        idempotency_key=f"bundle-{external_user_id}",
    )
    assert bundle_response.status_code == 200
    return connection_id


def test_create_only_connection_then_session_bundle_roundtrip_is_encrypted(
    client: TestClient,
    db_session: Session,
) -> None:
    _enable_marketplace(db_session)

    create_response = _post_json(
        client,
        "/v1/marketplace-connections",
        _create_connection_payload(),
        idempotency_key=None,
    )
    assert create_response.status_code == 200
    assert create_response.json()["status"] == "connecting"

    bundle_response = _post_json(
        client,
        "/v1/marketplace-connections/1/session-bundle",
        _bundle_payload(),
        idempotency_key="bundle-1",
    )

    assert bundle_response.status_code == 200
    assert bundle_response.json()["status"] == "connected"
    assert "secret-cookie" not in bundle_response.text
    assert "secret-token" not in bundle_response.text

    secret = db_session.scalar(select(MarketplaceSessionSecret))
    assert secret is not None
    assert "secret-cookie" not in secret.encrypted_cookie_bundle
    assert secret.key_version == "v1"


def test_new_marketplace_post_aliases_are_owner_scoped_and_hmac_protected(
    client: TestClient,
    db_session: Session,
) -> None:
    connection_id = _create_connected_marketplace(client, db_session)

    unauthenticated = client.post(
        f"/v1/marketplace-connections/{connection_id}/disconnect",
        json={"site_id": SITE_ID, "external_user_id": USER_ID},
    )
    wrong_owner = _post_json(
        client,
        f"/v1/marketplace-connections/{connection_id}/disconnect",
        {"site_id": SITE_ID, "external_user_id": OTHER_USER_ID},
        idempotency_key="disconnect-wrong-owner",
    )
    owner = _post_json(
        client,
        f"/v1/marketplace-connections/{connection_id}/disconnect",
        {"site_id": SITE_ID, "external_user_id": USER_ID},
        idempotency_key="disconnect-owner",
    )

    assert unauthenticated.status_code == 401
    assert wrong_owner.status_code == 404
    assert owner.status_code == 200
    assert owner.json()["status"] == "disconnected"


def test_reconnect_required_accepts_only_auth_expiry_reasons(
    client: TestClient,
    db_session: Session,
) -> None:
    connection_id = _create_connected_marketplace(client, db_session)

    invalid = _post_json(
        client,
        f"/v1/marketplace-connections/{connection_id}/reconnect-required",
        {"site_id": SITE_ID, "external_user_id": USER_ID, "reason": "captcha"},
        idempotency_key="reconnect-invalid",
    )
    expired = _post_json(
        client,
        f"/v1/marketplace-connections/{connection_id}/reconnect-required",
        {"site_id": SITE_ID, "external_user_id": USER_ID, "reason": "expired"},
        idempotency_key="reconnect-expired",
    )

    assert invalid.status_code == 422
    assert expired.status_code == 200
    assert expired.json()["status"] == "reconnect_required"
    assert expired.json()["reason"] == "expired"


def test_sync_session_items_are_idempotent_and_collections_are_owner_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    connection_id = _create_connected_marketplace(client, db_session)
    sync_payload = {
        "site_id": SITE_ID,
        "external_user_id": USER_ID,
        "connection_id": connection_id,
        "collection_type": "cart",
        "started_at": "2026-06-15T11:00:00Z",
    }

    first_sync = _post_json(
        client,
        "/v1/sync-sessions",
        sync_payload,
        idempotency_key="sync-1",
    )
    duplicate_sync = _post_json(
        client,
        "/v1/sync-sessions",
        sync_payload,
        idempotency_key="sync-1",
    )

    assert first_sync.status_code == 200
    assert duplicate_sync.status_code == 200
    assert duplicate_sync.json() == first_sync.json()
    sync_session_id = first_sync.json()["sync_session_id"]

    item_payload = {
        "site_id": SITE_ID,
        "external_user_id": USER_ID,
        "items": [
            {
                "external_item_id": "cart-line-1",
                "source_product_id": "ozon-sku-1",
                "product_url": "https://ozon.ru/product/1",
                "title": "Test product",
                "quantity": 1,
            }
        ],
    }
    first_items = _post_json(
        client,
        f"/v1/sync-sessions/{sync_session_id}/items",
        item_payload,
        idempotency_key="sync-items-1",
    )
    duplicate_items = _post_json(
        client,
        f"/v1/sync-sessions/{sync_session_id}/items",
        item_payload,
        idempotency_key="sync-items-1",
    )
    own_collections = client.get(
        f"/v1/collections?site_id={SITE_ID}&external_user_id={USER_ID}",
        headers=_signed_headers(),
    )
    other_collections = client.get(
        f"/v1/collections?site_id={SITE_ID}&external_user_id={OTHER_USER_ID}",
        headers=_signed_headers(),
    )

    assert first_items.status_code == 200
    assert duplicate_items.status_code == 200
    assert duplicate_items.json() == first_items.json()
    assert db_session.scalar(select(ImportedItem).where()) is not None
    assert len(db_session.scalars(select(ImportedItem)).all()) == 1
    assert own_collections.status_code == 200
    assert own_collections.json()["items"][0]["items"][0]["external_item_id"] == (
        "cart-line-1"
    )
    assert "secret-cookie" not in own_collections.text
    assert other_collections.status_code == 200
    assert other_collections.json()["items"] == []


def test_sync_finish_auth_failure_sets_reconnect_required(
    client: TestClient,
    db_session: Session,
) -> None:
    connection_id = _create_connected_marketplace(client, db_session)
    sync_response = _post_json(
        client,
        "/v1/sync-sessions",
        {
            "site_id": SITE_ID,
            "external_user_id": USER_ID,
            "connection_id": connection_id,
            "collection_type": "favorites",
            "started_at": "2026-06-15T11:00:00Z",
        },
        idempotency_key="sync-finish",
    )
    sync_session_id = sync_response.json()["sync_session_id"]

    finish_response = _post_json(
        client,
        f"/v1/sync-sessions/{sync_session_id}/finish",
        {
            "site_id": SITE_ID,
            "external_user_id": USER_ID,
            "status": "failed",
            "reason": "login_required",
            "finished_at": "2026-06-15T11:05:00Z",
        },
        idempotency_key="sync-finish-login-required",
    )

    assert finish_response.status_code == 200
    assert finish_response.json()["status"] == "failed"
    connection = db_session.get(MarketplaceConnection, connection_id)
    assert connection is not None
    assert connection.status == "reconnect_required"
    assert connection.reconnect_reason == "login_required"


def test_sync_session_rejects_invalid_or_foreign_connection(
    client: TestClient,
    db_session: Session,
) -> None:
    foreign_connection_id = _create_connected_marketplace(
        client,
        db_session,
        external_user_id=OTHER_USER_ID,
    )

    response = _post_json(
        client,
        "/v1/sync-sessions",
        {
            "site_id": SITE_ID,
            "external_user_id": USER_ID,
            "connection_id": foreign_connection_id,
            "collection_type": "cart",
            "started_at": "2026-06-15T11:00:00Z",
        },
        idempotency_key="foreign-sync",
    )

    assert response.status_code == 404


def test_idempotency_key_conflict_is_rejected(
    client: TestClient,
    db_session: Session,
) -> None:
    connection_id = _create_connected_marketplace(client, db_session)
    first = {
        "site_id": SITE_ID,
        "external_user_id": USER_ID,
        "connection_id": connection_id,
        "collection_type": "cart",
        "started_at": "2026-06-15T11:00:00Z",
    }
    second = first | {"collection_type": "favorites"}

    ok = _post_json(client, "/v1/sync-sessions", first, idempotency_key="same-key")
    conflict = _post_json(
        client,
        "/v1/sync-sessions",
        second,
        idempotency_key="same-key",
    )

    assert ok.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "idempotency_key_conflict"


def test_product_compare_is_owner_scoped_and_local_only(
    client: TestClient,
    db_session: Session,
) -> None:
    product = TrackedProduct(
        id=10,
        source="ozon",
        external_product_id="ozon-sku-10",
        canonical_url="https://ozon.ru/product/10",
        region_code="default",
        product_name="Compare product",
        last_price=Decimal("1000.00"),
        currency="RUB",
    )
    store = Store(store_code="dns", display_name="DNS", enabled=True)
    db_session.add_all([product, store])
    db_session.flush()
    db_session.add(
        UserProductSubscription(
            site_id=SITE_ID,
            external_user_id=USER_ID,
            tracked_product=product,
            is_active=True,
        )
    )
    match_group = ProductMatchGroup(
        tracked_product=product,
        match_key="match-10",
        confidence="exact",
        label="same_product",
    )
    db_session.add(match_group)
    db_session.flush()
    db_session.add(
        ProductOffer(
            match_group=match_group,
            store=store,
            source_code="dns",
            external_product_id="dns-sku-10",
            product_url="https://dns-shop.local/product/10",
            title="Compare product",
            price=Decimal("950.00"),
            currency="RUB",
            availability="in_stock",
            match_confidence="exact",
            match_label="same_product",
        )
    )
    db_session.commit()

    owner = client.get(
        f"/v1/products/10/compare?site_id={SITE_ID}&external_user_id={USER_ID}",
        headers=_signed_headers(),
    )
    other = client.get(
        f"/v1/products/10/compare?site_id={SITE_ID}&external_user_id={OTHER_USER_ID}",
        headers=_signed_headers(),
    )

    assert owner.status_code == 200
    assert owner.json()["tracked_product_id"] == 10
    assert owner.json()["offers"] == [
        {
            "offer_id": 1,
            "store_code": "dns",
            "store_display_name": "DNS",
            "source_code": "dns",
            "region_code": "default",
            "product_url": "https://dns-shop.local/product/10",
            "title": "Compare product",
            "price": "950.00",
            "currency": "RUB",
            "availability": "in_stock",
            "match_confidence": "exact",
            "match_label": "same_product",
            "match_score": None,
            "match_status": None,
            "match_explanation": None,
            "effective_price": None,
        }
    ]
    assert other.status_code == 404


def test_delete_imported_collection_is_owner_scoped_and_redacted(
    client: TestClient,
    db_session: Session,
) -> None:
    collection = ImportedCollection(
        site_id=SITE_ID,
        external_user_id=USER_ID,
        source="ozon",
        region_code="default",
        collection_type="cart",
        status="active",
    )
    collection.items.append(
        ImportedItem(
            external_item_id="cart-line-secret",
            product_url="https://ozon.ru/product/secret",
            title="Imported product",
            raw_json={"cookie": "secret-cookie", "token": "secret-token"},
        )
    )
    db_session.add(collection)
    db_session.commit()

    other = client.delete(
        f"/v1/collections/{collection.id}?site_id={SITE_ID}&external_user_id={OTHER_USER_ID}",
        headers=_signed_headers(),
    )
    owner = client.delete(
        f"/v1/collections/{collection.id}?site_id={SITE_ID}&external_user_id={USER_ID}",
        headers=_signed_headers(),
    )
    collections = client.get(
        f"/v1/collections?site_id={SITE_ID}&external_user_id={USER_ID}",
        headers=_signed_headers(),
    )

    db_session.refresh(collection)

    assert other.status_code == 404
    assert owner.status_code == 200
    assert owner.json() == {
        "collection_id": collection.id,
        "status": "archived",
    }
    assert collection.status == "archived"
    assert collections.status_code == 200
    assert collections.json()["items"] == []
    assert "secret-cookie" not in owner.text
    assert "secret-token" not in owner.text
