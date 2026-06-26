import hashlib
import hmac
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.clients import cashback_api
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    PriceHistory,
    Store,
    StoreSource,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

SECRET = "incoming-test-secret"
SITE_ID = "savelloclub.ru"
USER_ID = "wp:savelloclub.ru:123"
OTHER_USER_ID = "wp:savelloclub.ru:456"
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
        "X-Savello-Site": site_id,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": _signature(timestamp, raw_body),
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
def client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> Iterator[TestClient]:
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(SECRET),
    )
    monkeypatch.setattr(
        config.settings,
        "product_image_public_base_url",
        "https://cdn.example.com/images",
        raising=False,
    )
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW)

    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _product(
    session: Session,
    *,
    product_id: int,
    title: str = "Palit Видеокарта GeForce RTX 5070",
    source: str = "ozon",
    source_display_name: str | None = "Ozon",
    external_product_id: str | None = None,
    region_code: str = "default",
    price: str = "809.70",
    currency: str = "USD",
    availability: bool = True,
) -> TrackedProduct:
    product = TrackedProduct(
        id=product_id,
        source=source,
        source_display_name=source_display_name,
        external_product_id=external_product_id or f"sku-{product_id}",
        canonical_url=f"https://example.local/product/{product_id}",
        region_code=region_code,
        product_name=title,
        image_url=f"https://saved.example/products/{product_id}.jpg",
        image_object_key=f"products/{product_id}.jpg",
        last_price=Decimal(price),
        currency=currency,
        last_availability=availability,
        last_checked_at=datetime(2026, 6, 8, 10, 0, 0),
    )
    session.add(product)
    session.commit()
    return product


def _subscription(
    session: Session,
    *,
    product_id: int,
    external_user_id: str = USER_ID,
    is_active: bool = True,
) -> UserProductSubscription:
    product = session.get(TrackedProduct, product_id)
    region_code = product.region_code if product is not None else "default"
    subscription = UserProductSubscription(
        site_id=SITE_ID,
        external_user_id=external_user_id,
        tracked_product_id=product_id,
        region_code=region_code,
        is_active=is_active,
    )
    session.add(subscription)
    session.commit()
    return subscription


def _history_point(
    session: Session,
    *,
    product_id: int,
    price: str,
    fetched_at: datetime,
    currency: str = "USD",
) -> PriceHistory:
    point = PriceHistory(
        tracked_product_id=product_id,
        price_current=Decimal(price),
        price_old=None,
        currency=currency,
        availability=True,
        fetched_at=fetched_at,
    )
    session.add(point)
    session.commit()
    return point


def _snapshot(
    session: Session,
    *,
    product_id: int,
    **overrides,
) -> TrackedProductCashback:
    values = {
        "tracked_product_id": product_id,
        "cashback_status": "partner_exact",
        "confidence": "exact",
        "display_policy": "show_exact_rate",
    }
    values.update(overrides)
    snapshot = TrackedProductCashback(**values)
    session.add(snapshot)
    session.commit()
    return snapshot


def _ui_url(
    *,
    external_user_id: str = USER_ID,
    include_chart_summary: bool | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    url = f"/v1/watchlist/ui?site_id={SITE_ID}&external_user_id={external_user_id}"
    if include_chart_summary is not None:
        url += f"&include_chart_summary={str(include_chart_summary).lower()}"
    if limit is not None:
        url += f"&limit={limit}"
    if offset is not None:
        url += f"&offset={offset}"
    return url


def test_watchlist_ui_returns_card_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add(
        Store(
            store_code="ozon",
            display_name="Ozon",
            enabled=True,
            logo_url="https://cdn.example.com/logos/ozon.svg",
        )
    )
    db_session.commit()
    _product(db_session, product_id=1)
    subscription = _subscription(db_session, product_id=1)

    response = client.get(_ui_url(include_chart_summary=False), headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "subscription_id": subscription.id,
                "tracked_product_id": 1,
                "region_code": "default",
                "price_region_text": "Цена для региона default",
                "title": "Palit Видеокарта GeForce RTX 5070",
                "source_display_name": "Ozon",
                "source_logo_url": "https://cdn.example.com/logos/ozon.svg",
                "image_url": "https://cdn.example.com/images/products/1.jpg",
                "current_price": "809.70",
                "currency": "USD",
                "availability": True,
                "cashback": {
                    "cashback_status": "unknown",
                    "cashback_available": False,
                    "display_policy": "cashback_unknown_requires_check",
                },
            }
        ],
        "pagination": {
            "limit": 50,
            "offset": 0,
            "total": 1,
            "has_more": False,
        },
        "user_region": {
            "region_code": "default",
            "is_default": True,
        },
    }


def test_watchlist_ui_returns_admin_store_brand_for_source_code(
    client: TestClient,
    db_session: Session,
) -> None:
    store = Store(
        store_code="dns_shop_ru",
        display_name="DNS",
        enabled=True,
        logo_url="https://cdn.example.com/logos/dns.svg",
    )
    db_session.add(store)
    db_session.flush()
    db_session.add(
        StoreSource(
            store=store,
            source_code="dns_shop_ru_default",
            display_name="DNS source",
            enabled=True,
            source_type="api",
            domains_json=["dns-shop.ru", "www.dns-shop.ru"],
        )
    )
    db_session.commit()
    _product(
        db_session,
        product_id=1,
        source="dns_shop_ru_default",
        source_display_name=None,
    )
    _subscription(db_session, product_id=1)

    response = client.get(_ui_url(include_chart_summary=False), headers=_headers())

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["source_display_name"] == "DNS"
    assert item["source_logo_url"] == "https://cdn.example.com/logos/dns.svg"


def test_watchlist_ui_keeps_same_product_regions_separate(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(
        db_session,
        product_id=1,
        external_product_id="shared-sku",
        region_code="msk",
        price="1000.00",
        availability=True,
    )
    _product(
        db_session,
        product_id=2,
        external_product_id="shared-sku",
        region_code="spb",
        price="1200.00",
        availability=False,
    )
    _subscription(db_session, product_id=1)
    _subscription(db_session, product_id=2)
    _history_point(
        db_session,
        product_id=1,
        price="900.00",
        fetched_at=datetime(2026, 6, 6, 10, 0, 0),
    )
    _history_point(
        db_session,
        product_id=1,
        price="1000.00",
        fetched_at=datetime(2026, 6, 8, 10, 0, 0),
    )
    _history_point(
        db_session,
        product_id=2,
        price="1300.00",
        fetched_at=datetime(2026, 6, 6, 10, 0, 0),
    )
    _history_point(
        db_session,
        product_id=2,
        price="1200.00",
        fetched_at=datetime(2026, 6, 8, 10, 0, 0),
    )

    response = client.get(_ui_url(), headers=_headers())

    assert response.status_code == 200
    items = response.json()["items"]
    assert [
        (
            item["region_code"],
            item["price_region_text"],
            item["current_price"],
            item["availability"],
            item["chart_summary"]["trend"],
        )
        for item in items
    ] == [
        ("msk", "Цена для региона msk", "1000.00", True, "above_usual"),
        ("spb", "Цена для региона spb", "1200.00", False, "below_usual"),
    ]


def test_watchlist_ui_default_includes_chart_summary(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(db_session, product_id=1)
    _subscription(db_session, product_id=1)
    _history_point(
        db_session,
        product_id=1,
        price="790.10",
        fetched_at=datetime(2026, 6, 6, 10, 0, 0),
    )
    _history_point(
        db_session,
        product_id=1,
        price="809.70",
        fetched_at=datetime(2026, 6, 8, 10, 0, 0),
    )

    response = client.get(_ui_url(), headers=_headers())

    assert response.status_code == 200
    assert response.json()["items"][0]["chart_summary"] == {
        "trend": "above_usual",
        "delta_vs_avg_percent": "1.23",
        "headline": "Сейчас дороже, чем обычно, на 1.23%",
    }


def test_watchlist_ui_can_omit_chart_summary(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(db_session, product_id=1)
    _subscription(db_session, product_id=1)
    _history_point(
        db_session,
        product_id=1,
        price="809.70",
        fetched_at=datetime(2026, 6, 8, 10, 0, 0),
    )

    response = client.get(_ui_url(include_chart_summary=False), headers=_headers())

    assert response.status_code == 200
    assert "chart_summary" not in response.json()["items"][0]


def test_watchlist_ui_filters_foreign_and_inactive_items(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(db_session, product_id=1, title="Own active")
    _product(db_session, product_id=2, title="Own inactive")
    _product(db_session, product_id=3, title="Other user")
    _subscription(db_session, product_id=1)
    _subscription(db_session, product_id=2, is_active=False)
    _subscription(db_session, product_id=3, external_user_id=OTHER_USER_ID)

    response = client.get(_ui_url(include_chart_summary=False), headers=_headers())

    assert response.status_code == 200
    assert [item["tracked_product_id"] for item in response.json()["items"]] == [1]
    assert response.json()["pagination"]["total"] == 1


def test_watchlist_ui_includes_cashback_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(db_session, product_id=1)
    _subscription(db_session, product_id=1)
    _snapshot(
        db_session,
        product_id=1,
        merchant_id="ozon-merchant",
        merchant_name="Ozon",
        network="admitad",
        offer_id="offer-1",
        user_cashback_exact_rate=Decimal("3.5"),
        expected_cashback_exact=Decimal("28.34"),
        effective_price=Decimal("781.36"),
    )

    response = client.get(_ui_url(include_chart_summary=False), headers=_headers())

    assert response.status_code == 200
    cashback = response.json()["items"][0]["cashback"]
    assert cashback["cashback_status"] == "partner_exact"
    assert cashback["cashback_available"] is True
    assert cashback["merchant_id"] == "ozon-merchant"
    assert cashback["merchant_name"] == "Ozon"
    assert cashback["network"] == "admitad"
    assert cashback["offer_id"] == "offer-1"
    assert cashback["user_cashback_exact_rate"] == "3.5"
    assert cashback["expected_cashback_exact"] == "28.34"
    assert cashback["effective_price"] == "781.36"


def test_watchlist_ui_requires_hmac(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(db_session, product_id=1)
    _subscription(db_session, product_id=1)

    response = client.get(_ui_url())

    assert response.status_code == 401


def test_watchlist_ui_does_not_call_cashback_api_client(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _product(db_session, product_id=1)
    _subscription(db_session, product_id=1)

    def fail_init(*args, **kwargs):
        raise AssertionError("Watchlist UI endpoint must not call cashback API.")

    monkeypatch.setattr(cashback_api.CashbackAPIClient, "__init__", fail_init)

    response = client.get(_ui_url(include_chart_summary=False), headers=_headers())

    assert response.status_code == 200


def test_watchlist_ui_paginates_items(
    client: TestClient,
    db_session: Session,
) -> None:
    _product(db_session, product_id=1, title="First")
    _product(db_session, product_id=2, title="Second")
    _product(db_session, product_id=3, title="Third")
    _subscription(db_session, product_id=1)
    _subscription(db_session, product_id=2)
    _subscription(db_session, product_id=3)

    response = client.get(
        _ui_url(include_chart_summary=False, limit=1, offset=1),
        headers=_headers(),
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["Second"]
    assert response.json()["pagination"] == {
        "limit": 1,
        "offset": 1,
        "total": 3,
        "has_more": True,
    }
