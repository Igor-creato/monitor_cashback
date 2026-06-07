import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    FetchJob,
    TrackedProduct,
    UserProductSubscription,
)

SECRET = "incoming-test-secret"
SITE_ID = "savelloclub.ru"
NOW = 1_800_000_000


def _signature(timestamp: str, raw_body: bytes, secret: str = SECRET) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()


def _headers(raw_body: bytes = b"", *, site_id: str = SITE_ID) -> dict[str, str]:
    timestamp = str(NOW)
    return {
        "Content-Type": "application/json",
        "X-Savello-Site": site_id,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": _signature(timestamp, raw_body),
    }


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _post_payload(
    *,
    external_user_id: str = "wp:savelloclub.ru:123",
    product_url: str = "https://testshop.local/product/123?utm_source=x",
) -> dict:
    return {
        "site_id": SITE_ID,
        "external_user_id": external_user_id,
        "product_url": product_url,
        "target_price": 5000,
        "target_effective_price": None,
        "region_code": "default",
    }


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
def client(monkeypatch, db_session: Session) -> Iterator[TestClient]:
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(SECRET),
    )
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW)

    if hasattr(db, "get_db"):
        app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _post_watchlist_item(client: TestClient, payload: dict) -> object:
    body = _json_body(payload)
    return client.post(
        "/v1/watchlist/items",
        content=body,
        headers=_headers(body, site_id=payload["site_id"]),
    )


def test_watchlist_post_without_hmac_is_rejected(client: TestClient) -> None:
    body = _json_body(_post_payload())

    response = client.post(
        "/v1/watchlist/items",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


def test_post_creates_product_and_subscription(
    client: TestClient,
    db_session: Session,
) -> None:
    response = _post_watchlist_item(client, _post_payload())

    assert response.status_code == 200
    assert response.json() == {
        "subscription_id": 1,
        "tracked_product_id": 1,
        "site_id": SITE_ID,
        "external_user_id": "wp:savelloclub.ru:123",
        "product_url": "https://testshop.local/product/123",
        "source": "testshop",
        "external_product_id": "123",
        "region_code": "default",
        "target_price": "5000.00",
        "target_effective_price": None,
        "is_active": True,
    }
    assert db_session.scalar(select(func.count(TrackedProduct.id))) == 1
    assert db_session.scalar(select(func.count(UserProductSubscription.id))) == 1
    assert db_session.scalar(select(func.count(FetchJob.id))) == 0


def test_duplicate_url_with_utm_does_not_create_second_product(
    client: TestClient,
    db_session: Session,
) -> None:
    first_response = _post_watchlist_item(
        client,
        _post_payload(product_url="https://testshop.local/product/123?utm_source=x"),
    )
    second_response = _post_watchlist_item(
        client,
        _post_payload(product_url="https://testshop.local/product/123?utm_source=y"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["subscription_id"] == second_response.json()[
        "subscription_id"
    ]
    assert db_session.scalar(select(func.count(TrackedProduct.id))) == 1
    assert db_session.scalar(select(func.count(UserProductSubscription.id))) == 1


def test_second_user_creates_second_subscription_without_second_product(
    client: TestClient,
    db_session: Session,
) -> None:
    first_response = _post_watchlist_item(client, _post_payload())
    second_response = _post_watchlist_item(
        client,
        _post_payload(external_user_id="wp:savelloclub.ru:456"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["tracked_product_id"] == second_response.json()[
        "tracked_product_id"
    ]
    assert first_response.json()["subscription_id"] != second_response.json()[
        "subscription_id"
    ]
    assert db_session.scalar(select(func.count(TrackedProduct.id))) == 1
    assert db_session.scalar(select(func.count(UserProductSubscription.id))) == 2


def test_get_returns_only_current_users_active_subscriptions(
    client: TestClient,
) -> None:
    active_response = _post_watchlist_item(client, _post_payload())
    inactive_response = _post_watchlist_item(
        client,
        _post_payload(product_url="https://demo-store.local/goods/sku-42"),
    )
    other_user_response = _post_watchlist_item(
        client,
        _post_payload(
            external_user_id="wp:savelloclub.ru:456",
            product_url="https://example-market.local/item/abc-777",
        ),
    )
    inactive_id = inactive_response.json()["subscription_id"]
    body = _json_body({"is_active": False})
    patch_response = client.patch(
        f"/v1/watchlist/items/{inactive_id}?site_id={SITE_ID}"
        "&external_user_id=wp:savelloclub.ru:123",
        content=body,
        headers=_headers(body),
    )

    response = client.get(
        "/v1/watchlist/items?site_id=savelloclub.ru"
        "&external_user_id=wp:savelloclub.ru:123",
        headers=_headers(),
    )

    assert active_response.status_code == 200
    assert inactive_response.status_code == 200
    assert other_user_response.status_code == 200
    assert patch_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["limit"] == 50
    assert response.json()["items"] == [active_response.json()]


def test_patch_changes_only_allowed_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    post_response = _post_watchlist_item(client, _post_payload())
    subscription_id = post_response.json()["subscription_id"]
    original_subscription = db_session.get(UserProductSubscription, subscription_id)
    assert original_subscription is not None
    original_product_id = original_subscription.tracked_product_id
    body = _json_body(
        {
            "target_price": 4500,
            "target_effective_price": 4200,
            "is_active": False,
            "tracked_product_id": 999,
            "site_id": "evil.example",
            "external_user_id": "wp:evil.example:1",
        }
    )

    response = client.patch(
        f"/v1/watchlist/items/{subscription_id}?site_id={SITE_ID}"
        "&external_user_id=wp:savelloclub.ru:123",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 200
    assert response.json()["target_price"] == "4500.00"
    assert response.json()["target_effective_price"] == "4200.00"
    assert response.json()["is_active"] is False
    db_session.refresh(original_subscription)
    assert original_subscription.tracked_product_id == original_product_id
    assert original_subscription.site_id == SITE_ID
    assert original_subscription.external_user_id == "wp:savelloclub.ru:123"
    assert original_subscription.target_price == Decimal("4500.00")
    assert original_subscription.target_effective_price == Decimal("4200.00")


def test_delete_soft_deletes_subscription(client: TestClient) -> None:
    post_response = _post_watchlist_item(client, _post_payload())
    subscription_id = post_response.json()["subscription_id"]

    delete_response = client.delete(
        f"/v1/watchlist/items/{subscription_id}?site_id={SITE_ID}"
        "&external_user_id=wp:savelloclub.ru:123",
        headers=_headers(),
    )
    get_response = client.get(
        f"/v1/watchlist/items?site_id={SITE_ID}"
        "&external_user_id=wp:savelloclub.ru:123",
        headers=_headers(),
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["is_active"] is False
    assert get_response.status_code == 200
    assert get_response.json()["items"] == []


def test_unsupported_source_returns_400(client: TestClient) -> None:
    response = _post_watchlist_item(
        client,
        _post_payload(product_url="https://unknown.local/product/123"),
    )

    assert response.status_code == 400
