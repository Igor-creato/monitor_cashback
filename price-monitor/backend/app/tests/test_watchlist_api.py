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
from app.clients import cashback_api
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    FetchJob,
    TrackedProduct,
    TrackedProductCashback,
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


def _get_watchlist_items(
    client: TestClient,
    *,
    external_user_id: str = "wp:savelloclub.ru:123",
) -> object:
    return client.get(
        f"/v1/watchlist/items?site_id={SITE_ID}&external_user_id={external_user_id}",
        headers=_headers(),
    )


def _snapshot(
    db_session: Session,
    tracked_product_id: int,
    **overrides,
) -> TrackedProductCashback:
    values = {
        "tracked_product_id": tracked_product_id,
        "cashback_status": "partner_exact",
        "confidence": "exact",
        "display_policy": "show_exact_rate",
    }
    values.update(overrides)
    snapshot = TrackedProductCashback(**values)
    db_session.add(snapshot)
    db_session.commit()
    return snapshot


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
    assert response.json()["items"] == [
        {
            **active_response.json(),
            "cashback": {
                "cashback_status": "unknown",
                "cashback_available": False,
                "merchant_id": None,
                "merchant_name": None,
                "network": None,
                "offer_id": None,
                "user_cashback_exact_rate": None,
                "user_cashback_min_rate": None,
                "user_cashback_max_rate": None,
                "expected_cashback_exact": None,
                "expected_cashback_min": None,
                "expected_cashback_max": None,
                "effective_price": None,
                "effective_price_conservative": None,
                "confidence": None,
                "display_policy": "cashback_unknown_requires_check",
                "message": None,
            },
        }
    ]


def test_get_without_cashback_snapshot_returns_unknown(client: TestClient) -> None:
    post_response = _post_watchlist_item(client, _post_payload())

    response = _get_watchlist_items(client)

    assert post_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["items"][0]["cashback"] == {
        "cashback_status": "unknown",
        "cashback_available": False,
        "merchant_id": None,
        "merchant_name": None,
        "network": None,
        "offer_id": None,
        "user_cashback_exact_rate": None,
        "user_cashback_min_rate": None,
        "user_cashback_max_rate": None,
        "expected_cashback_exact": None,
        "expected_cashback_min": None,
        "expected_cashback_max": None,
        "effective_price": None,
        "effective_price_conservative": None,
        "confidence": None,
        "display_policy": "cashback_unknown_requires_check",
        "message": None,
    }


def test_get_no_partner_snapshot_returns_cashback_unavailable(
    client: TestClient,
    db_session: Session,
) -> None:
    post_response = _post_watchlist_item(client, _post_payload())
    tracked_product_id = post_response.json()["tracked_product_id"]
    _snapshot(
        db_session,
        tracked_product_id,
        cashback_status="no_partner",
        confidence="none",
        display_policy="cashback_unavailable",
        message="Партнёр не найден",
    )

    response = _get_watchlist_items(client)

    assert response.status_code == 200
    assert response.json()["items"][0]["cashback"] == {
        "cashback_status": "no_partner",
        "cashback_available": False,
        "merchant_id": None,
        "merchant_name": None,
        "network": None,
        "offer_id": None,
        "user_cashback_exact_rate": None,
        "user_cashback_min_rate": None,
        "user_cashback_max_rate": None,
        "expected_cashback_exact": None,
        "expected_cashback_min": None,
        "expected_cashback_max": None,
        "effective_price": None,
        "effective_price_conservative": None,
        "confidence": "none",
        "display_policy": "cashback_unavailable",
        "message": "Партнёр не найден",
    }


def test_get_partner_exact_snapshot_returns_exact_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    post_response = _post_watchlist_item(client, _post_payload())
    tracked_product_id = post_response.json()["tracked_product_id"]
    _snapshot(
        db_session,
        tracked_product_id,
        cashback_status="partner_exact",
        merchant_id="ali_001",
        merchant_name="AliExpress",
        network="admitad",
        offer_id="29562",
        user_cashback_exact_rate=Decimal("3.5"),
        expected_cashback_exact=Decimal("350.00"),
        effective_price=Decimal("9650.00"),
        confidence="exact",
        display_policy="show_exact_rate",
        message="Точная ставка",
    )

    response = _get_watchlist_items(client)

    assert response.status_code == 200
    assert response.json()["items"][0]["cashback"] == {
        "cashback_status": "partner_exact",
        "cashback_available": True,
        "merchant_id": "ali_001",
        "merchant_name": "AliExpress",
        "network": "admitad",
        "offer_id": "29562",
        "user_cashback_exact_rate": "3.5",
        "user_cashback_min_rate": None,
        "user_cashback_max_rate": None,
        "expected_cashback_exact": "350.00",
        "expected_cashback_min": None,
        "expected_cashback_max": None,
        "effective_price": "9650.00",
        "effective_price_conservative": None,
        "confidence": "exact",
        "display_policy": "show_exact_rate",
        "message": "Точная ставка",
    }


def test_get_partner_estimated_snapshot_returns_range_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    post_response = _post_watchlist_item(client, _post_payload())
    tracked_product_id = post_response.json()["tracked_product_id"]
    _snapshot(
        db_session,
        tracked_product_id,
        cashback_status="partner_estimated",
        merchant_id="ali_001",
        merchant_name="AliExpress",
        network="admitad",
        offer_id="29562",
        user_cashback_min_rate=Decimal("0.2660"),
        user_cashback_max_rate=Decimal("4.8440"),
        expected_cashback_min=Decimal("26.60"),
        expected_cashback_max=Decimal("484.40"),
        effective_price_conservative=Decimal("9973.40"),
        confidence="medium",
        display_policy="show_range_use_min_for_effective_price",
        message="Точная ставка зависит от категории товара",
    )

    response = _get_watchlist_items(client)

    assert response.status_code == 200
    assert response.json()["items"][0]["cashback"] == {
        "cashback_status": "partner_estimated",
        "cashback_available": True,
        "merchant_id": "ali_001",
        "merchant_name": "AliExpress",
        "network": "admitad",
        "offer_id": "29562",
        "user_cashback_exact_rate": None,
        "user_cashback_min_rate": "0.266",
        "user_cashback_max_rate": "4.844",
        "expected_cashback_exact": None,
        "expected_cashback_min": "26.60",
        "expected_cashback_max": "484.40",
        "effective_price": None,
        "effective_price_conservative": "9973.40",
        "confidence": "medium",
        "display_policy": "show_range_use_min_for_effective_price",
        "message": "Точная ставка зависит от категории товара",
    }


def test_get_does_not_call_cashback_api_client(
    client: TestClient,
    monkeypatch,
) -> None:
    _post_watchlist_item(client, _post_payload())

    def fail_init(*args, **kwargs):
        raise AssertionError("GET must not instantiate CashbackAPIClient.")

    monkeypatch.setattr(cashback_api.CashbackAPIClient, "__init__", fail_init)

    response = _get_watchlist_items(client)

    assert response.status_code == 200


def test_get_does_not_return_other_users_cashback_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    _post_watchlist_item(
        client,
        _post_payload(product_url="https://testshop.local/product/123"),
    )
    other_response = _post_watchlist_item(
        client,
        _post_payload(
            external_user_id="wp:savelloclub.ru:456",
            product_url="https://demo-store.local/goods/sku-42",
        ),
    )
    _snapshot(
        db_session,
        other_response.json()["tracked_product_id"],
        cashback_status="partner_exact",
        merchant_id="other_merchant",
        confidence="exact",
        display_policy="show_exact_rate",
    )

    response = _get_watchlist_items(client)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["tracked_product_id"] == 1
    assert response.json()["items"][0]["cashback"]["merchant_id"] is None


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
