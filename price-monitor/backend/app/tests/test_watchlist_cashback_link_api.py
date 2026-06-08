import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.watchlist as watchlist_api
import app.db as db
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.services.deeplink import DeeplinkCreationError, DeeplinkUnavailable

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
        "Content-Type": "application/json",
        "X-Savello-Site": site_id,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": _signature(timestamp, raw_body),
    }


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


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
    subscription_id: int = 10,
    tracked_product_id: int = 1,
    external_user_id: str = USER_ID,
    is_active: bool = True,
) -> UserProductSubscription:
    subscription = UserProductSubscription(
        id=subscription_id,
        site_id=SITE_ID,
        external_user_id=external_user_id,
        tracked_product_id=tracked_product_id,
        is_active=is_active,
    )
    session.add(subscription)
    session.commit()
    return subscription


def _cashback_snapshot(
    session: Session,
    *,
    tracked_product_id: int = 1,
    cashback_status: str = "partner_estimated",
    merchant_id: str | None = "merchant-101",
) -> TrackedProductCashback:
    snapshot = TrackedProductCashback(
        tracked_product_id=tracked_product_id,
        cashback_status=cashback_status,
        merchant_id=merchant_id,
        confidence="medium",
        display_policy="show_range_use_min_for_effective_price",
    )
    session.add(snapshot)
    session.commit()
    return snapshot


def _cashback_link_body(
    *,
    external_user_id: str = USER_ID,
) -> bytes:
    return _json_body(
        {
            "site_id": SITE_ID,
            "external_user_id": external_user_id,
        }
    )


def test_own_active_subscription_gets_cashback_url(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session, cashback_status="partner_estimated")

    def fake_create_cashback_deeplink(
        tracked_product_id,
        subscription_id,
        event_id=None,
        *,
        session=None,
        client=None,
    ):
        assert tracked_product_id == 1
        assert subscription_id == 10
        assert session is db_session
        assert event_id is None
        assert client is None
        return "https://go.example/cashback"

    monkeypatch.setattr(
        watchlist_api,
        "create_cashback_deeplink",
        fake_create_cashback_deeplink,
        raising=False,
    )
    body = _cashback_link_body()

    response = client.post(
        "/v1/watchlist/items/10/cashback-link",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 200
    assert response.json() == {
        "cashback_url": "https://go.example/cashback",
        "link_type": "deeplink",
        "cashback_status": "partner_estimated",
    }


def test_foreign_subscription_returns_404(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session, external_user_id=OTHER_USER_ID)
    _cashback_snapshot(db_session)

    def fail_create_cashback_deeplink(*args, **kwargs):
        raise AssertionError("Foreign subscription must not create deeplink.")

    monkeypatch.setattr(
        watchlist_api,
        "create_cashback_deeplink",
        fail_create_cashback_deeplink,
        raising=False,
    )
    body = _cashback_link_body()

    response = client.post(
        "/v1/watchlist/items/10/cashback-link",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 404


def test_no_partner_returns_422(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session, cashback_status="no_partner", merchant_id=None)

    monkeypatch.setattr(
        watchlist_api,
        "create_cashback_deeplink",
        lambda *args, **kwargs: DeeplinkUnavailable("no_partner"),
        raising=False,
    )
    body = _cashback_link_body()

    response = client.post(
        "/v1/watchlist/items/10/cashback-link",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Cashback is unavailable for this product"}


def test_cashback_api_error_returns_503(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session)

    def fail_create_cashback_deeplink(*args, **kwargs):
        raise DeeplinkCreationError("cashback_api_unavailable")

    monkeypatch.setattr(
        watchlist_api,
        "create_cashback_deeplink",
        fail_create_cashback_deeplink,
        raising=False,
    )
    body = _cashback_link_body()

    response = client.post(
        "/v1/watchlist/items/10/cashback-link",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 503


def test_cashback_link_requires_hmac(
    client: TestClient,
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session)
    body = _cashback_link_body()

    response = client.post(
        "/v1/watchlist/items/10/cashback-link",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
