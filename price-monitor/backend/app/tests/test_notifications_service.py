from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import (
    NotificationEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.services.notifications import evaluate_price_alerts


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.notifications as notifications

    monkeypatch.setattr(notifications, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _tracked_product(
    session: Session,
    *,
    product_id: int = 1,
    last_price: Decimal = Decimal("1000.00"),
) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://testshop.local/product/{product_id}",
        region_code="default",
        last_price=last_price,
        currency="RUB",
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _subscription(
    session: Session,
    *,
    subscription_id: int = 1,
    tracked_product_id: int = 1,
    target_price: Decimal | None = None,
    target_effective_price: Decimal | None = None,
    is_active: bool = True,
) -> UserProductSubscription:
    subscription = UserProductSubscription(
        id=subscription_id,
        site_id="site-1",
        external_user_id="user-1",
        tracked_product_id=tracked_product_id,
        target_price=target_price,
        target_effective_price=target_effective_price,
        is_active=is_active,
    )
    session.add(subscription)
    session.commit()
    return subscription


def _cashback_snapshot(
    session: Session,
    *,
    tracked_product_id: int = 1,
    effective_price: Decimal | None = None,
    effective_price_conservative: Decimal | None = None,
    expected_cashback_max: Decimal | None = None,
    commission_min: Decimal | None = None,
    commission_max: Decimal | None = None,
) -> TrackedProductCashback:
    snapshot = TrackedProductCashback(
        tracked_product_id=tracked_product_id,
        cashback_status="partner_estimated",
        commission_rate_type="percent",
        commission_min=commission_min,
        commission_max=commission_max,
        user_share=Decimal("0.5"),
        expected_cashback_max=expected_cashback_max,
        effective_price=effective_price,
        effective_price_conservative=effective_price_conservative,
        confidence="medium",
        display_policy="show_range_use_min_for_effective_price",
    )
    session.add(snapshot)
    session.commit()
    return snapshot


def _event_count(session: Session) -> int:
    return session.scalar(select(func.count(NotificationEvent.id))) or 0


def _payload(event: NotificationEvent) -> dict:
    return json.loads(event.payload_json)


def test_target_price_reached_event_is_created(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(db_session, target_price=Decimal("1000.00"))

    events = evaluate_price_alerts(1)

    assert len(events) == 1
    event = db_session.scalar(select(NotificationEvent))
    assert event is not None
    assert event.event_type == "target_price_reached"
    assert event.status == "pending"
    assert event.site_id == "site-1"
    assert event.external_user_id == "user-1"
    assert event.subscription_id == 1
    assert event.tracked_product_id == 1
    assert event.sent_at is None
    assert event.error_text is None
    assert _payload(event) == {
        "currency": "RUB",
        "event_type": "target_price_reached",
        "last_price": "900.00",
        "subscription_id": 1,
        "target_price": "1000.00",
        "tracked_product_id": 1,
    }


def test_target_effective_price_reached_event_is_created_from_exact_cashback(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session, target_effective_price=Decimal("950.00"))
    _cashback_snapshot(db_session, effective_price=Decimal("940.00"))

    events = evaluate_price_alerts(1)

    assert [event.event_type for event in events] == [
        "target_effective_price_reached"
    ]
    event = db_session.scalar(select(NotificationEvent))
    assert event is not None
    assert _payload(event) == {
        "currency": "RUB",
        "effective_price": "940.00",
        "effective_price_source": "effective_price",
        "event_type": "target_effective_price_reached",
        "last_price": "1000.00",
        "subscription_id": 1,
        "target_effective_price": "950.00",
        "tracked_product_id": 1,
    }


def test_target_effective_price_reached_event_is_created_from_conservative_range(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session, target_effective_price=Decimal("980.00"))
    _cashback_snapshot(
        db_session,
        effective_price_conservative=Decimal("975.00"),
        expected_cashback_max=Decimal("120.00"),
        commission_min=Decimal("5.0"),
        commission_max=Decimal("12.0"),
    )

    events = evaluate_price_alerts(1)

    assert [event.event_type for event in events] == [
        "target_effective_price_reached"
    ]
    event = db_session.scalar(select(NotificationEvent))
    assert event is not None
    assert _payload(event)["effective_price"] == "975.00"
    assert _payload(event)["effective_price_source"] == "effective_price_conservative"


def test_max_cashback_is_not_used_for_effective_target(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session, target_effective_price=Decimal("950.00"))
    _cashback_snapshot(
        db_session,
        effective_price_conservative=Decimal("975.00"),
        expected_cashback_max=Decimal("120.00"),
        commission_min=Decimal("5.0"),
        commission_max=Decimal("12.0"),
    )

    events = evaluate_price_alerts(1)

    assert events == []
    assert _event_count(db_session) == 0


def test_zero_min_cashback_does_not_create_false_effective_gain(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session, target_effective_price=Decimal("999.00"))
    _cashback_snapshot(
        db_session,
        effective_price_conservative=Decimal("1000.00"),
        expected_cashback_max=Decimal("120.00"),
        commission_min=Decimal("0.0"),
        commission_max=Decimal("12.0"),
    )

    events = evaluate_price_alerts(1)

    assert events == []
    assert _event_count(db_session) == 0


def test_duplicate_event_within_24_hours_is_not_created(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(db_session, target_price=Decimal("1000.00"))
    db_session.add(
        NotificationEvent(
            site_id="site-1",
            external_user_id="user-1",
            subscription_id=1,
            tracked_product_id=1,
            event_type="target_price_reached",
            status="pending",
            payload_json="{}",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
    )
    db_session.commit()

    events = evaluate_price_alerts(1)

    assert events == []
    assert _event_count(db_session) == 1


def test_inactive_subscription_is_ignored(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(
        db_session,
        target_price=Decimal("1000.00"),
        target_effective_price=Decimal("950.00"),
        is_active=False,
    )
    _cashback_snapshot(db_session, effective_price=Decimal("940.00"))

    events = evaluate_price_alerts(1)

    assert events == []
    assert _event_count(db_session) == 0
