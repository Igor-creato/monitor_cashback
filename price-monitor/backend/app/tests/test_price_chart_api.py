import hashlib
import hmac
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
import app.services.price_chart as price_chart
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    PriceHistory,
    TrackedProduct,
    UserProductSubscription,
)
from app.repositories.price_history_repository import PriceHistoryPoint

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
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW)
    monkeypatch.setattr(
        price_chart,
        "current_utc_datetime",
        lambda: datetime(2026, 6, 8, 12, 0, 0),
    )

    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _tracked_product(session: Session, product_id: int = 1) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://testshop.local/product/{product_id}",
        region_code="default",
        product_name="Palit Видеокарта GeForce RTX 5070",
        last_price=Decimal("809.70"),
        currency="USD",
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _subscription(
    session: Session,
    *,
    tracked_product_id: int = 1,
    external_user_id: str = USER_ID,
    is_active: bool = True,
) -> UserProductSubscription:
    subscription = UserProductSubscription(
        site_id=SITE_ID,
        external_user_id=external_user_id,
        tracked_product_id=tracked_product_id,
        is_active=is_active,
    )
    session.add(subscription)
    session.commit()
    return subscription


def _history_point(
    session: Session,
    *,
    tracked_product_id: int = 1,
    price_current: str,
    currency: str = "USD",
    fetched_at: datetime,
) -> PriceHistory:
    point = PriceHistory(
        tracked_product_id=tracked_product_id,
        price_current=Decimal(price_current),
        price_old=None,
        currency=currency,
        availability=True,
        fetched_at=fetched_at,
    )
    session.add(point)
    session.commit()
    return point


def _chart_url(
    tracked_product_id: int = 1,
    *,
    external_user_id: str = USER_ID,
    days: int | None = None,
    granularity: str | None = None,
    currency: str | None = None,
) -> str:
    url = (
        f"/v1/products/{tracked_product_id}/price-chart"
        f"?site_id={SITE_ID}&external_user_id={external_user_id}"
    )
    if days is not None:
        url += f"&days={days}"
    if granularity is not None:
        url += f"&granularity={granularity}"
    if currency is not None:
        url += f"&currency={currency}"
    return url


def test_own_active_subscription_gets_price_chart(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _history_point(
        db_session,
        price_current="750.00",
        fetched_at=datetime(2026, 5, 25, 10, 0, 0),
    )
    _history_point(
        db_session,
        price_current="800.00",
        fetched_at=datetime(2026, 5, 26, 10, 0, 0),
    )
    _history_point(
        db_session,
        price_current="850.00",
        fetched_at=datetime(2026, 5, 27, 10, 0, 0),
    )

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "tracked_product_id": 1,
        "title": "Palit Видеокарта GeForce RTX 5070",
        "currency": "USD",
        "summary": {
            "current_price": "850.00",
            "avg_price": "800.00",
            "min_price": "750.00",
            "max_price": "850.00",
            "delta_vs_avg_percent": "6.25",
            "trend": "above_usual",
        },
        "series": [
            {"ts": "2026-05-25T10:00:00Z", "price": "750.00"},
            {"ts": "2026-05-26T10:00:00Z", "price": "800.00"},
            {"ts": "2026-05-27T10:00:00Z", "price": "850.00"},
        ],
        "y_axis": {
            "min": "750.00",
            "avg": "800.00",
            "max": "850.00",
        },
        "labels": {
            "headline": "Сейчас дороже, чем обычно, на 6.25%",
        },
    }


def test_foreign_product_price_chart_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session, external_user_id=OTHER_USER_ID)
    _history_point(
        db_session,
        price_current="850.00",
        fetched_at=datetime(2026, 5, 27, 10, 0, 0),
    )

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "Product chart not found."}


def test_inactive_subscription_price_chart_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session, is_active=False)

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "Product chart not found."}


def test_price_chart_summary_calculates_avg_min_max_and_delta(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    for price, fetched_at in [
        ("743.20", datetime(2026, 5, 25, 10, 0, 0)),
        ("793.20", datetime(2026, 5, 26, 10, 0, 0)),
        ("843.20", datetime(2026, 5, 27, 10, 0, 0)),
    ]:
        _history_point(db_session, price_current=price, fetched_at=fetched_at)

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "current_price": "843.20",
        "avg_price": "793.20",
        "min_price": "743.20",
        "max_price": "843.20",
        "delta_vs_avg_percent": "6.30",
        "trend": "above_usual",
    }
    assert body["y_axis"] == {"min": "743.20", "avg": "793.20", "max": "843.20"}


def test_price_chart_trend_below_usual_when_current_below_average(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    for price, fetched_at in [
        ("900.00", datetime(2026, 5, 25, 10, 0, 0)),
        ("800.00", datetime(2026, 5, 26, 10, 0, 0)),
        ("700.00", datetime(2026, 5, 27, 10, 0, 0)),
    ]:
        _history_point(db_session, price_current=price, fetched_at=fetched_at)

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 200
    assert response.json()["summary"]["trend"] == "below_usual"
    assert response.json()["summary"]["delta_vs_avg_percent"] == "-12.50"
    assert response.json()["labels"] == {
        "headline": "Сейчас дешевле, чем обычно, на 12.5%",
    }


def test_price_chart_no_data_for_empty_history(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "tracked_product_id": 1,
        "title": "Palit Видеокарта GeForce RTX 5070",
        "currency": "USD",
        "summary": {
            "current_price": None,
            "avg_price": None,
            "min_price": None,
            "max_price": None,
            "delta_vs_avg_percent": None,
            "trend": "no_data",
        },
        "series": [],
        "y_axis": {"min": None, "avg": None, "max": None},
        "labels": {"headline": "Недостаточно данных для графика"},
    }


def test_price_chart_days_above_90_is_rejected(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)

    response = client.get(_chart_url(days=91), headers=_headers())

    assert response.status_code == 422


def test_price_chart_days_filters_series(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.price_chart as price_chart

    now = datetime(2026, 6, 8, 12, 0, 0)
    monkeypatch.setattr(price_chart, "current_utc_datetime", lambda: now)
    _tracked_product(db_session)
    _subscription(db_session)
    _history_point(
        db_session,
        price_current="700.00",
        fetched_at=now - timedelta(days=40),
    )
    _history_point(
        db_session,
        price_current="800.00",
        fetched_at=now - timedelta(days=2),
    )

    response = client.get(_chart_url(days=30), headers=_headers())

    assert response.status_code == 200
    assert response.json()["series"] == [
        {"ts": "2026-06-06T12:00:00Z", "price": "800.00"},
    ]


def test_price_chart_daily_granularity_uses_last_price_per_day(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    for price, fetched_at in [
        ("100.00", datetime(2026, 5, 25, 8, 0, 0)),
        ("120.00", datetime(2026, 5, 25, 18, 0, 0)),
        ("90.00", datetime(2026, 5, 26, 9, 0, 0)),
    ]:
        _history_point(db_session, price_current=price, fetched_at=fetched_at)

    response = client.get(_chart_url(granularity="daily"), headers=_headers())

    assert response.status_code == 200
    assert response.json()["series"] == [
        {"ts": "2026-05-25T00:00:00Z", "price": "120.00"},
        {"ts": "2026-05-26T00:00:00Z", "price": "90.00"},
    ]
    assert response.json()["summary"]["avg_price"] == "105.00"
    assert response.json()["summary"]["trend"] == "below_usual"


def test_price_chart_currency_filters_history(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _history_point(
        db_session,
        price_current="100.00",
        currency="EUR",
        fetched_at=datetime(2026, 5, 25, 10, 0, 0),
    )
    _history_point(
        db_session,
        price_current="200.00",
        currency="USD",
        fetched_at=datetime(2026, 5, 26, 10, 0, 0),
    )

    response = client.get(_chart_url(currency="USD"), headers=_headers())

    assert response.status_code == 200
    assert response.json()["currency"] == "USD"
    assert response.json()["series"] == [
        {"ts": "2026-05-26T10:00:00Z", "price": "200.00"},
    ]


def test_price_chart_requires_hmac(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)

    response = client.get(_chart_url())

    assert response.status_code == 401


def test_price_chart_response_does_not_include_cashback(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _history_point(
        db_session,
        price_current="850.00",
        fetched_at=datetime(2026, 5, 27, 10, 0, 0),
    )

    response = client.get(_chart_url(), headers=_headers())

    assert response.status_code == 200
    assert "cashback" not in str(response.json()).lower()


def test_price_chart_endpoint_uses_price_history_repository(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.price_chart as price_chart

    _tracked_product(db_session)
    _subscription(db_session)
    now = datetime(2026, 6, 8, 12, 0, 0)
    calls = []

    class FakePriceHistoryRepository:
        def get_price_points(self, *, tracked_product_id, fetched_at_from, currency):
            calls.append(
                {
                    "tracked_product_id": tracked_product_id,
                    "fetched_at_from": fetched_at_from,
                    "currency": currency,
                }
            )
            return [
                PriceHistoryPoint(
                    id=101,
                    tracked_product_id=tracked_product_id,
                    price_current=Decimal("777.00"),
                    price_old=None,
                    currency="USD",
                    availability=True,
                    seller_name=None,
                    fetched_at=datetime(2026, 5, 27, 10, 0, 0),
                )
            ]

    fake_repository = FakePriceHistoryRepository()
    monkeypatch.setattr(price_chart, "current_utc_datetime", lambda: now)
    monkeypatch.setattr(
        price_chart,
        "get_price_history_repository",
        lambda session: fake_repository,
    )

    response = client.get(_chart_url(currency="USD"), headers=_headers())

    assert response.status_code == 200
    assert response.json()["series"] == [
        {"ts": "2026-05-27T10:00:00Z", "price": "777.00"},
    ]
    assert calls == [
        {
            "tracked_product_id": 1,
            "fetched_at_from": now - timedelta(days=30),
            "currency": "USD",
        }
    ]
