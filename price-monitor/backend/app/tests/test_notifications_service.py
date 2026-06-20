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
    MarketplaceConnection,
    MarketplaceSyncSession,
    NotificationEvent,
    NotificationPreference,
    PriceHistory,
    ProductMatchGroup,
    ProductOffer,
    Store,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.services.notifications import (
    dispatch_pending_notifications,
    evaluate_connection_alerts,
    evaluate_price_alerts,
)
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserPriceMonitorLimits,
)

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


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


def _price_history(
    session: Session,
    *,
    tracked_product_id: int = 1,
    price: Decimal,
    fetched_at: datetime,
    availability: bool = True,
) -> PriceHistory:
    point = PriceHistory(
        tracked_product_id=tracked_product_id,
        region_code="default",
        price_current=price,
        price_old=None,
        currency="RUB",
        availability=availability,
        fetched_at=fetched_at.replace(tzinfo=None),
    )
    session.add(point)
    session.commit()
    return point


def _cheaper_offer(session: Session, *, price: Decimal) -> ProductOffer:
    store = Store(
        store_code="better-shop",
        display_name="Better Shop",
        homepage_url="https://better-shop.test",
    )
    session.add(store)
    session.flush()
    group = ProductMatchGroup(
        tracked_product_id=1,
        match_key="same-sku",
        confidence="exact",
        label="same_product",
    )
    session.add(group)
    session.flush()
    offer = ProductOffer(
        match_group=group,
        store=store,
        source_code="feed",
        external_product_id="better-1",
        product_url="https://better-shop.test/product/1",
        title="Same product",
        price=price,
        currency="RUB",
        availability="in_stock",
        effective_price=None,
        match_confidence="exact",
        match_label="same_product",
        raw_json={"match_score": 100},
    )
    session.add(offer)
    session.commit()
    return offer


def _limits(alerts_per_day: int):
    def provider(site_id: str, external_user_id: str) -> UserPriceMonitorLimits:
        return UserPriceMonitorLimits(
            external_user_id=external_user_id,
            tariff="test",
            limits=PriceMonitorLimitValues(
                max_tracked_products=10,
                history_days=90,
                min_fetch_interval_minutes=60,
                alerts_per_day=alerts_per_day,
                manual_refresh_per_day=10,
                browser_fallback_allowed=False,
            ),
            cashback=CashbackLimitValues(
                user_share=Decimal("0.5"),
                cashback_currency="RUB",
            ),
        )

    return provider


def _event_count(session: Session) -> int:
    return session.scalar(select(func.count(NotificationEvent.id))) or 0


def _payload(event: NotificationEvent | None) -> dict:
    assert event is not None
    return json.loads(event.payload_json)


def test_target_price_reached_event_is_created(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(db_session, target_price=Decimal("1000.00"))

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert len(events) == 1
    event = db_session.scalar(select(NotificationEvent))
    assert event is not None
    assert event.event_type == "target_price_reached"
    assert event.channel == "email"
    assert event.dedup_key == "subscription:1:target_price_reached:900.00"
    assert event.status == "pending"
    assert event.site_id == "site-1"
    assert event.external_user_id == "user-1"
    assert event.subscription_id == 1
    assert event.tracked_product_id == 1
    assert event.sent_at is None
    assert event.error_text is None
    assert _payload(event)["target_price"] == "1000.00"


def test_target_effective_price_reached_event_is_created_from_exact_cashback(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session, target_effective_price=Decimal("950.00"))
    _cashback_snapshot(db_session, effective_price=Decimal("940.00"))

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert [event.event_type for event in events] == ["target_effective_price_reached"]
    event = db_session.scalar(select(NotificationEvent))
    assert _payload(event)["effective_price"] == "940.00"
    assert _payload(event)["effective_price_source"] == "effective_price"


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

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert [event.event_type for event in events] == ["target_effective_price_reached"]
    event = db_session.scalar(select(NotificationEvent))
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

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

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

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert events == []
    assert _event_count(db_session) == 0


def test_duplicate_event_within_cooldown_is_not_created(
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
            channel="email",
            dedup_key="subscription:1:target_price_reached:900.00",
            status="pending",
            payload_json="{}",
            created_at=(NOW - timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert events == []
    assert _event_count(db_session) == 1


def test_price_drop_uses_user_threshold_preference(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(db_session)
    db_session.add(
        NotificationPreference(
            site_id="site-1",
            external_user_id="user-1",
            event_type="price_drop",
            channel="email",
            enabled=True,
            drop_threshold_percent=Decimal("7.00"),
        )
    )
    _price_history(
        db_session,
        price=Decimal("1000.00"),
        fetched_at=NOW - timedelta(hours=2),
    )
    _price_history(db_session, price=Decimal("900.00"), fetched_at=NOW)

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert [event.event_type for event in events] == ["price_drop"]
    event = db_session.scalar(select(NotificationEvent))
    assert _payload(event)["drop_percent"] == "10.00"


def test_price_drop_below_threshold_is_ignored(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("960.00"))
    _subscription(db_session)
    _price_history(
        db_session,
        price=Decimal("1000.00"),
        fetched_at=NOW - timedelta(hours=2),
    )
    _price_history(db_session, price=Decimal("960.00"), fetched_at=NOW)

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert events == []
    assert _event_count(db_session) == 0


def test_new_minimum_events_are_created_for_7_30_90_day_windows(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("800.00"))
    _subscription(db_session)
    _price_history(
        db_session,
        price=Decimal("900.00"),
        fetched_at=NOW - timedelta(days=6),
    )
    _price_history(
        db_session,
        price=Decimal("950.00"),
        fetched_at=NOW - timedelta(days=29),
    )
    _price_history(
        db_session,
        price=Decimal("990.00"),
        fetched_at=NOW - timedelta(days=89),
    )
    _price_history(db_session, price=Decimal("800.00"), fetched_at=NOW)

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert [event.event_type for event in events] == [
        "price_drop",
        "new_minimum_7d",
        "new_minimum_30d",
        "new_minimum_90d",
    ]


def test_cheaper_offer_event_uses_same_product_offer(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session)
    _cheaper_offer(db_session, price=Decimal("850.00"))

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert [event.event_type for event in events] == ["cheaper_offer_found"]
    payload = _payload(db_session.scalar(select(NotificationEvent)))
    assert payload["offer_price"] == "850.00"
    assert payload["store_code"] == "better-shop"


def test_back_in_stock_event_is_created_from_history_transition(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("1000.00"))
    _subscription(db_session)
    _price_history(
        db_session,
        price=Decimal("1000.00"),
        fetched_at=NOW - timedelta(hours=2),
        availability=False,
    )
    _price_history(
        db_session,
        price=Decimal("1000.00"),
        fetched_at=NOW,
        availability=True,
    )

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert [event.event_type for event in events] == ["back_in_stock"]


def test_disabled_preference_suppresses_event(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(db_session, target_price=Decimal("1000.00"))
    db_session.add(
        NotificationPreference(
            site_id="site-1",
            external_user_id="user-1",
            event_type="target_price_reached",
            channel="email",
            enabled=False,
        )
    )
    db_session.commit()

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert events == []
    assert _event_count(db_session) == 0


def test_daily_limit_creates_skipped_event_without_delivery(
    db_session: Session,
) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(db_session, target_price=Decimal("1000.00"))

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(0))

    assert [event.status for event in events] == ["skipped"]
    event = db_session.scalar(select(NotificationEvent))
    assert event is not None
    assert event.status == "skipped"
    assert event.next_attempt_at is None


def test_inactive_subscription_is_ignored(db_session: Session) -> None:
    _tracked_product(db_session, last_price=Decimal("900.00"))
    _subscription(
        db_session,
        target_price=Decimal("1000.00"),
        target_effective_price=Decimal("950.00"),
        is_active=False,
    )
    _cashback_snapshot(db_session, effective_price=Decimal("940.00"))

    events = evaluate_price_alerts(1, now=NOW, limits_provider=_limits(10))

    assert events == []
    assert _event_count(db_session) == 0


def test_connection_reconnect_required_event_is_user_level(
    db_session: Session,
) -> None:
    connection = MarketplaceConnection(
        site_id="site-1",
        external_user_id="user-1",
        marketplace="ozon",
        region_code="default",
        status="reconnect_required",
        scope_json=["cart_read"],
        consent_version="v1",
        consented_at=NOW.replace(tzinfo=None),
        reconnect_reason="login_required",
    )
    db_session.add(connection)
    db_session.commit()

    events = evaluate_connection_alerts(
        connection.id,
        now=NOW,
        reason="login_required",
        limits_provider=_limits(10),
    )

    assert [event.event_type for event in events] == ["reconnect_required"]
    event = db_session.scalar(select(NotificationEvent))
    assert event is not None
    assert event.subscription_id is None
    assert event.tracked_product_id is None
    assert event.connection_id == connection.id


def test_connection_repeated_sync_failure_requires_three_consecutive_failures(
    db_session: Session,
) -> None:
    connection = MarketplaceConnection(
        site_id="site-1",
        external_user_id="user-1",
        marketplace="ozon",
        region_code="default",
        status="sync_failed_retryable",
        scope_json=["cart_read"],
        consent_version="v1",
        consented_at=NOW.replace(tzinfo=None),
        reconnect_reason="timeout",
    )
    db_session.add(connection)
    db_session.flush()
    for index in range(3):
        db_session.add(
            MarketplaceSyncSession(
                connection_id=connection.id,
                site_id="site-1",
                external_user_id="user-1",
                source="ozon",
                collection_type="cart",
                status="failed",
                started_at=(NOW - timedelta(minutes=index)).replace(tzinfo=None),
                finished_at=(NOW - timedelta(minutes=index)).replace(tzinfo=None),
                reason="timeout",
            )
        )
    db_session.commit()

    events = evaluate_connection_alerts(
        connection.id,
        now=NOW,
        reason="timeout",
        limits_provider=_limits(10),
    )

    assert [event.event_type for event in events] == ["sync_failed_repeated"]
    assert _payload(events[0])["failure_count"] == 3


def test_dispatch_pending_notifications_marks_success_sent(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    event = NotificationEvent(
        site_id="site-1",
        external_user_id="user-1",
        subscription_id=1,
        tracked_product_id=1,
        event_type="target_price_reached",
        channel="email",
        dedup_key="subscription:1:target_price_reached:900.00",
        payload_json=json.dumps({"event_type": "target_price_reached"}),
        created_at=NOW.replace(tzinfo=None),
    )
    db_session.add(event)
    db_session.commit()

    class FakeClient:
        def send_price_monitor_notification(self, payload):
            assert payload["notification_id"] == event.id
            assert payload["template"] == "price_monitor_target_price_reached"
            return {"status": "queued"}

    result = dispatch_pending_notifications(limit=10, now=NOW, client=FakeClient())

    db_session.refresh(event)
    assert result == {"sent": 1, "failed": 0, "retry": 0}
    assert event.status == "sent"
    assert event.sent_at == NOW.replace(tzinfo=None)


def test_dispatch_pending_notifications_retries_transient_error(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _subscription(db_session)
    event = NotificationEvent(
        site_id="site-1",
        external_user_id="user-1",
        subscription_id=1,
        tracked_product_id=1,
        event_type="target_price_reached",
        channel="email",
        dedup_key="subscription:1:target_price_reached:900.00",
        payload_json="{}",
        created_at=NOW.replace(tzinfo=None),
    )
    db_session.add(event)
    db_session.commit()

    class FakeClient:
        def send_price_monitor_notification(self, payload):
            raise RuntimeError("temporary")

    result = dispatch_pending_notifications(limit=10, now=NOW, client=FakeClient())

    db_session.refresh(event)
    assert result == {"sent": 0, "failed": 0, "retry": 1}
    assert event.status == "pending"
    assert event.delivery_attempts == 1
    assert event.next_attempt_at == (NOW + timedelta(minutes=5)).replace(tzinfo=None)
