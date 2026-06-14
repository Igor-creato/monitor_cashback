import hashlib
import hmac
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config, incoming_hmac
from app.dev.seed_demo_data import (
    DEMO_EXTERNAL_USER_ID,
    DEMO_SITE_ID,
    DemoSeedEnvironmentError,
    seed_demo_data,
)
from app.main import app
from app.models.monitoring import (
    PriceHistory,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

SECRET = "incoming-test-secret"
NOW_TS = 1_800_000_000
FIXED_NOW = datetime(2026, 6, 14, 12, 0, 0)


def _signature(timestamp: str, raw_body: bytes, secret: str = SECRET) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()


def _headers(raw_body: bytes = b"") -> dict[str, str]:
    timestamp = str(NOW_TS)
    return {
        "X-Savello-Site": DEMO_SITE_ID,
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
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", DEMO_SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(SECRET),
    )
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW_TS)

    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


def _demo_products(session: Session) -> list[TrackedProduct]:
    return list(
        session.scalars(
            select(TrackedProduct).order_by(TrackedProduct.source.asc()),
        ),
    )


def test_seed_refuses_test_env_without_writes(db_session: Session) -> None:
    with pytest.raises(DemoSeedEnvironmentError, match="APP_ENV=development"):
        seed_demo_data(db_session, app_env="test", now=FIXED_NOW)

    assert _count(db_session, TrackedProduct) == 0
    assert _count(db_session, UserProductSubscription) == 0
    assert _count(db_session, PriceHistory) == 0
    assert _count(db_session, TrackedProductCashback) == 0


def test_seed_refuses_production_env_without_writes(db_session: Session) -> None:
    with pytest.raises(DemoSeedEnvironmentError, match="APP_ENV=development"):
        seed_demo_data(db_session, app_env="production", now=FIXED_NOW)

    assert _count(db_session, TrackedProduct) == 0
    assert _count(db_session, UserProductSubscription) == 0
    assert _count(db_session, PriceHistory) == 0
    assert _count(db_session, TrackedProductCashback) == 0


def test_seed_creates_two_products_subscriptions_cashback_and_history(
    db_session: Session,
) -> None:
    result = seed_demo_data(db_session, app_env="development", now=FIXED_NOW)

    products = _demo_products(db_session)
    assert result.site_id == DEMO_SITE_ID
    assert result.external_user_id == DEMO_EXTERNAL_USER_ID
    assert result.product_count == 2
    assert result.subscription_count == 2
    assert result.history_point_count == 60
    assert {product.source for product in products} == {"dns", "ozon"}
    assert {product.source_display_name for product in products} == {"DNS", "Ozon"}
    assert all(product.product_name for product in products)
    assert all(
        (product.image_url or "").startswith("https://demo.invalid/")
        for product in products
    )
    assert all(product.currency == "RUB" for product in products)
    assert all(product.last_checked_at == FIXED_NOW for product in products)

    subscriptions = list(db_session.scalars(select(UserProductSubscription)))
    assert len(subscriptions) == 2
    assert all(subscription.site_id == DEMO_SITE_ID for subscription in subscriptions)
    assert all(
        subscription.external_user_id == DEMO_EXTERNAL_USER_ID
        for subscription in subscriptions
    )
    assert all(subscription.is_active is True for subscription in subscriptions)

    histories_by_product = {
        product.id: list(
            db_session.scalars(
                select(PriceHistory)
                .where(PriceHistory.tracked_product_id == product.id)
                .order_by(PriceHistory.fetched_at.asc()),
            ),
        )
        for product in products
    }
    assert {len(points) for points in histories_by_product.values()} == {30}
    for product in products:
        latest_point = histories_by_product[product.id][-1]
        assert latest_point.fetched_at == FIXED_NOW
        assert product.last_price == latest_point.price_current

    cashback_by_source = {product.source: product.cashback for product in products}
    assert cashback_by_source["ozon"] is not None
    assert cashback_by_source["ozon"].cashback_status == "partner_estimated"
    assert cashback_by_source["dns"] is not None
    assert cashback_by_source["dns"].cashback_status == "no_partner"
    assert cashback_by_source["dns"].confidence == "none"


def test_seed_is_idempotent_for_products_subscriptions_and_history(
    db_session: Session,
) -> None:
    first = seed_demo_data(db_session, app_env="development", now=FIXED_NOW)
    second = seed_demo_data(db_session, app_env="development", now=FIXED_NOW)

    assert second.tracked_product_ids == first.tracked_product_ids
    assert second.subscription_ids == first.subscription_ids
    assert _count(db_session, TrackedProduct) == 2
    assert _count(db_session, UserProductSubscription) == 2
    assert _count(db_session, PriceHistory) == 60
    assert _count(db_session, TrackedProductCashback) == 2


def test_seeded_chart_api_returns_data_for_demo_user(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.price_chart as price_chart

    monkeypatch.setattr(price_chart, "current_utc_datetime", lambda: FIXED_NOW)
    result = seed_demo_data(db_session, app_env="development", now=FIXED_NOW)
    tracked_product_id = result.tracked_product_ids[0]

    response = client.get(
        f"/v1/products/{tracked_product_id}/price-chart"
        f"?site_id={DEMO_SITE_ID}&external_user_id={DEMO_EXTERNAL_USER_ID}",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tracked_product_id"] == tracked_product_id
    assert body["title"]
    assert body["currency"] == "RUB"
    assert len(body["series"]) == 30
    assert body["series"][0]["ts"] == "2026-05-16T12:00:00Z"
    assert body["series"][-1]["ts"] == "2026-06-14T12:00:00Z"
    assert Decimal(body["series"][0]["price"]) != Decimal(body["series"][-1]["price"])
