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
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    PriceHistory,
    TrackedProduct,
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
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW)

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
    price_current: str = "1000.00",
    price_old: str | None = None,
    currency: str = "RUB",
    availability: bool = True,
    fetched_at: datetime = datetime(2026, 6, 8, 10, 0, 0),
) -> PriceHistory:
    point = PriceHistory(
        tracked_product_id=tracked_product_id,
        price_current=Decimal(price_current),
        price_old=Decimal(price_old) if price_old is not None else None,
        currency=currency,
        availability=availability,
        fetched_at=fetched_at,
    )
    session.add(point)
    session.commit()
    return point


def _history_url(
    tracked_product_id: int = 1,
    *,
    external_user_id: str = USER_ID,
    days: int | None = None,
) -> str:
    url = (
        f"/v1/products/{tracked_product_id}/history"
        f"?site_id={SITE_ID}&external_user_id={external_user_id}"
    )
    if days is not None:
        url += f"&days={days}"
    return url


def test_own_product_history_is_available(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _history_point(db_session)

    response = client.get(_history_url(), headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "points": [
            {
                "price_current": "1000.00",
                "price_old": None,
                "currency": "RUB",
                "availability": True,
                "fetched_at": "2026-06-08T10:00:00",
            }
        ]
    }


def test_foreign_product_history_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session, external_user_id=OTHER_USER_ID)
    _history_point(db_session)

    response = client.get(_history_url(), headers=_headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "Product history not found."}


def test_empty_history_returns_empty_points(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)

    response = client.get(_history_url(), headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"points": []}


def test_days_filters_history_points(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.product_history as product_history

    now = datetime(2026, 6, 8, 12, 0, 0)
    monkeypatch.setattr(product_history, "current_utc_datetime", lambda: now)
    _tracked_product(db_session)
    _subscription(db_session)
    fresh_at = now - timedelta(days=2)
    old_at = now - timedelta(days=10)
    _history_point(
        db_session,
        price_current="900.00",
        fetched_at=old_at,
    )
    _history_point(
        db_session,
        price_current="1000.00",
        fetched_at=fresh_at,
    )

    response = client.get(_history_url(days=7), headers=_headers())

    assert response.status_code == 200
    assert response.json()["points"] == [
        {
            "price_current": "1000.00",
            "price_old": None,
            "currency": "RUB",
            "availability": True,
            "fetched_at": fresh_at.isoformat(),
        }
    ]


def test_days_above_30_is_rejected(client: TestClient, db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session)

    response = client.get(_history_url(days=31), headers=_headers())

    assert response.status_code == 422


def test_product_history_requires_hmac(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)

    response = client.get(_history_url())

    assert response.status_code == 401
