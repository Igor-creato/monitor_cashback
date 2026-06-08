from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.clients.cashback_api import CashbackAPIUnavailableError
from app.db import Base
from app.models.monitoring import (
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.services.deeplink import (
    DeeplinkCreationError,
    DeeplinkUnavailable,
    create_cashback_deeplink,
)


class FakeCashbackClient:
    def __init__(
        self,
        response: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or {"cashback_url": "https://go.example/click"}
        self.error = error
        self.payloads: list[dict] = []

    def create_deeplink(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def forbid_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_real_http(*args, **kwargs):
        raise AssertionError("Tests must not perform real HTTP requests.")

    monkeypatch.setattr(httpx.Client, "request", fail_real_http)


def _tracked_product(session: Session, *, product_id: int = 1) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id="sku-1",
        canonical_url="https://testshop.local/product/1",
        region_code="default",
        last_price=Decimal("1000.00"),
        currency="RUB",
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _subscription(
    session: Session,
    *,
    subscription_id: int = 10,
    tracked_product_id: int = 1,
    is_active: bool = True,
    external_user_id: str = "wp:savelloclub.test:77",
) -> UserProductSubscription:
    subscription = UserProductSubscription(
        id=subscription_id,
        site_id="savelloclub.test",
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
    cashback_status: str = "partner_exact",
    merchant_id: str | None = "101",
) -> TrackedProductCashback:
    snapshot = TrackedProductCashback(
        tracked_product_id=tracked_product_id,
        cashback_status=cashback_status,
        merchant_id=merchant_id,
        confidence="exact" if cashback_status == "partner_exact" else "medium",
        display_policy=(
            "show_exact_rate"
            if cashback_status == "partner_exact"
            else "show_range_use_min_for_effective_price"
        ),
    )
    session.add(snapshot)
    session.commit()
    return snapshot


def test_no_partner_does_not_create_deeplink(db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(
        db_session,
        cashback_status="no_partner",
        merchant_id=None,
    )
    client = FakeCashbackClient()

    result = create_cashback_deeplink(1, 10, session=db_session, client=client)

    assert isinstance(result, DeeplinkUnavailable)
    assert result.reason == "no_partner"
    assert client.payloads == []


def test_partner_exact_creates_deeplink(db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session, cashback_status="partner_exact")
    client = FakeCashbackClient({"cashback_url": "https://go.example/exact-click"})

    result = create_cashback_deeplink(1, 10, session=db_session, client=client)

    assert result == "https://go.example/exact-click"
    assert len(client.payloads) == 1
    assert client.payloads[0]["merchant_id"] == "101"
    assert client.payloads[0]["target_url"] == "https://testshop.local/product/1"
    assert client.payloads[0]["click_id"].startswith("pm_")


def test_partner_estimated_creates_deeplink(db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session, cashback_status="partner_estimated")
    client = FakeCashbackClient({"cashback_url": "https://go.example/estimated-click"})

    result = create_cashback_deeplink(1, 10, session=db_session, client=client)

    assert result == "https://go.example/estimated-click"
    assert client.payloads[0]["merchant_id"] == "101"


def test_inactive_subscription_is_rejected(db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session, is_active=False)
    _cashback_snapshot(db_session, cashback_status="partner_exact")
    client = FakeCashbackClient()

    result = create_cashback_deeplink(1, 10, session=db_session, client=client)

    assert isinstance(result, DeeplinkUnavailable)
    assert result.reason == "inactive_subscription"
    assert client.payloads == []


def test_click_id_does_not_contain_raw_external_user_id(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeUUID:
        hex = "abcd77efabcdabcdabcdabcdabcdabcd"

    monkeypatch.setattr("app.services.deeplink.uuid4", lambda: FakeUUID())
    raw_external_user_id = "wp:savelloclub.test:77"
    _tracked_product(db_session)
    _subscription(db_session, external_user_id=raw_external_user_id)
    _cashback_snapshot(db_session, cashback_status="partner_exact")
    client = FakeCashbackClient()

    create_cashback_deeplink(
        1,
        10,
        event_id="event-123",
        session=db_session,
        client=client,
    )

    click_id = client.payloads[0]["click_id"]
    assert click_id == "pm_abcd77efabcdabcdabcdabcdabcdabcd"
    assert raw_external_user_id not in click_id
    assert "event-123" not in click_id


def test_cashback_api_500_returns_typed_error(db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session, cashback_status="partner_exact")
    client = FakeCashbackClient(
        error=CashbackAPIUnavailableError("Cashback API is unavailable.")
    )

    with pytest.raises(DeeplinkCreationError) as exc_info:
        create_cashback_deeplink(1, 10, session=db_session, client=client)

    assert exc_info.value.reason == "cashback_api_unavailable"


def test_tests_forbid_real_http_requests(db_session: Session) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    _cashback_snapshot(db_session, cashback_status="partner_exact")

    with pytest.raises(AssertionError, match="real HTTP"):
        create_cashback_deeplink(1, 10, session=db_session)


def test_clicks_table_is_not_created(db_session: Session) -> None:
    table_names = set(inspect(db_session.bind).get_table_names())

    assert "clicks" not in table_names
