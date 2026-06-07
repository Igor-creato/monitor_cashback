from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.clients.cashback_api import CashbackAPIUnavailableError
from app.db import Base
from app.models.monitoring import TrackedProduct, TrackedProductCashback
from app.services.product_cashback import resolve_and_store_product_cashback


class FakeCashbackClient:
    def __init__(
        self,
        responses: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = responses or []
        self.error = error
        self.payloads: list[dict] = []

    def resolve_product(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("Unexpected resolve_product call.")
        return self.responses.pop(0)


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
def forbid_real_http(monkeypatch) -> None:
    def fail_real_http(*args, **kwargs):
        raise AssertionError("Tests must not perform real HTTP requests.")

    monkeypatch.setattr(httpx.Client, "request", fail_real_http)


def _tracked_product(
    session: Session,
    *,
    product_id: int = 1,
    last_price: Decimal | None = Decimal("1000.00"),
    currency: str | None = "RUB",
) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id="123",
        canonical_url="https://testshop.local/product/123",
        region_code="default",
        last_price=last_price,
        currency=currency,
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def test_successful_resolve_creates_snapshot(db_session: Session) -> None:
    _tracked_product(db_session)
    client = FakeCashbackClient(
        [
            {
                "cashback_status": "partner_exact",
                "merchant_id": "42",
                "merchant_name": "Test Merchant",
                "network": "admitad",
                "offer_id": "offer-42",
                "rate_id": "rate-1",
                "commission_rate_type": "percent",
                "commission_exact": "10",
                "user_share": "0.5",
                "message": "resolved",
            }
        ]
    )

    snapshot = resolve_and_store_product_cashback(
        1,
        session=db_session,
        client=client,
    )

    assert snapshot.tracked_product_id == 1
    assert snapshot.cashback_status == "partner_exact"
    assert snapshot.merchant_id == "42"
    assert snapshot.expected_cashback_exact == Decimal("50.00")
    assert snapshot.effective_price == Decimal("950.00")
    assert snapshot.confidence == "exact"
    assert snapshot.display_policy == "show_exact_rate"
    assert db_session.scalar(select(func.count(TrackedProductCashback.id))) == 1
    assert client.payloads == [
        {
            "url": "https://testshop.local/product/123",
            "canonical_url": "https://testshop.local/product/123",
            "source": "testshop",
            "external_product_id": "123",
            "price": "1000.00",
            "currency": "RUB",
            "region": "default",
        }
    ]


def test_repeated_resolve_updates_existing_snapshot(db_session: Session) -> None:
    _tracked_product(db_session)
    client = FakeCashbackClient(
        [
            {
                "cashback_status": "partner_exact",
                "merchant_id": "42",
                "commission_rate_type": "percent",
                "commission_exact": "10",
                "user_share": "0.5",
            },
            {
                "cashback_status": "partner_exact",
                "merchant_id": "99",
                "commission_rate_type": "percent",
                "commission_exact": "20",
                "user_share": "0.5",
            },
        ]
    )

    first = resolve_and_store_product_cashback(1, session=db_session, client=client)
    second = resolve_and_store_product_cashback(1, session=db_session, client=client)

    assert second.id == first.id
    assert second.merchant_id == "99"
    assert second.expected_cashback_exact == Decimal("100.00")
    assert second.effective_price == Decimal("900.00")
    assert db_session.scalar(select(func.count(TrackedProductCashback.id))) == 1


def test_no_partner_is_persisted(db_session: Session) -> None:
    _tracked_product(db_session)
    client = FakeCashbackClient(
        [{"cashback_status": "no_partner", "confidence": "none"}]
    )

    snapshot = resolve_and_store_product_cashback(
        1,
        price=Decimal("500.00"),
        session=db_session,
        client=client,
    )

    assert snapshot.cashback_status == "no_partner"
    assert snapshot.confidence == "none"
    assert snapshot.display_policy == "cashback_unavailable"
    assert snapshot.effective_price is None


def test_partner_estimated_persists_range(db_session: Session) -> None:
    _tracked_product(db_session)
    client = FakeCashbackClient(
        [
            {
                "cashback_status": "partner_estimated",
                "commission_rate_type": "percent",
                "commission_min": "5",
                "commission_max": "12",
                "user_share": "0.5",
            }
        ]
    )

    snapshot = resolve_and_store_product_cashback(1, session=db_session, client=client)

    assert snapshot.cashback_status == "partner_estimated"
    assert snapshot.expected_cashback_min == Decimal("25.00")
    assert snapshot.expected_cashback_max == Decimal("60.00")
    assert snapshot.effective_price is None
    assert snapshot.effective_price_conservative == Decimal("975.00")
    assert snapshot.display_policy == "show_range_use_min_for_effective_price"


def test_zero_min_rate_keeps_current_price_as_conservative_effective_price(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    client = FakeCashbackClient(
        [
            {
                "cashback_status": "partner_estimated",
                "commission_rate_type": "percent",
                "commission_min": "0",
                "commission_max": "12",
                "user_share": "0.5",
            }
        ]
    )

    snapshot = resolve_and_store_product_cashback(1, session=db_session, client=client)

    assert snapshot.expected_cashback_min == Decimal("0.00")
    assert snapshot.expected_cashback_max == Decimal("60.00")
    assert snapshot.effective_price_conservative == Decimal("1000.00")
    assert snapshot.display_policy == "show_possible_do_not_reduce_effective_price"


def test_api_500_does_not_delete_or_change_old_snapshot(db_session: Session) -> None:
    _tracked_product(db_session)
    old_client = FakeCashbackClient(
        [
            {
                "cashback_status": "partner_exact",
                "merchant_id": "42",
                "commission_rate_type": "percent",
                "commission_exact": "10",
                "user_share": "0.5",
            }
        ]
    )
    old_snapshot = resolve_and_store_product_cashback(
        1,
        session=db_session,
        client=old_client,
    )
    failing_client = FakeCashbackClient(
        error=CashbackAPIUnavailableError("Cashback API is unavailable.")
    )

    returned = resolve_and_store_product_cashback(
        1,
        session=db_session,
        client=failing_client,
    )

    db_session.refresh(old_snapshot)
    assert returned.id == old_snapshot.id
    assert old_snapshot.cashback_status == "partner_exact"
    assert old_snapshot.merchant_id == "42"
    assert old_snapshot.expected_cashback_exact == Decimal("50.00")
    assert db_session.scalar(select(func.count(TrackedProductCashback.id))) == 1


def test_api_failure_without_old_snapshot_creates_unknown_snapshot(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    failing_client = FakeCashbackClient(
        error=CashbackAPIUnavailableError("Cashback API is unavailable.")
    )

    snapshot = resolve_and_store_product_cashback(
        1,
        session=db_session,
        client=failing_client,
    )

    assert snapshot.cashback_status == "partner_unknown_product"
    assert snapshot.confidence == "none"
    assert snapshot.display_policy == "cashback_unknown_requires_check"
    assert snapshot.message == "cashback API unavailable; requires check"


def test_unknown_product_response_persists_partner_unknown_product(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    client = FakeCashbackClient(
        [
            {
                "cashback_status": "partner_unknown_product",
                "message": "product was not resolved",
            }
        ]
    )

    snapshot = resolve_and_store_product_cashback(1, session=db_session, client=client)

    assert snapshot.cashback_status == "partner_unknown_product"
    assert snapshot.confidence == "none"
    assert snapshot.display_policy == "cashback_unknown_requires_check"
    assert snapshot.message == "product was not resolved"
