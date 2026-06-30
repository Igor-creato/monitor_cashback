from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from price_monitor.domains.notifications.service import NotificationService
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import AlertEvent, OutboxEvent
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.domains.watchlist.service import WatchlistService


def test_price_target_alert_created_once_per_threshold_crossing(session: Session) -> None:
    item, product = _create_watchlist_item(session)
    product.current_price_minor = 9_999
    product.currency = "RUB"
    session.flush()

    service = NotificationService(session)
    first = service.evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )
    second = service.evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, 1, tzinfo=UTC),
    )

    assert len(first) == 1
    assert second == []
    assert first[0].dedup_key == f"price-target:{item.id}:10000:9999"
    assert first[0].status == "pending"

    alerts = session.scalars(select(AlertEvent)).all()
    assert len(alerts) == 1
    assert alerts[0].id == first[0].id

    outbox_events = session.scalars(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "notification.price_target_reached"
        )
    ).all()
    assert len(outbox_events) == 1
    assert outbox_events[0].aggregate_type == "alert_event"
    assert outbox_events[0].aggregate_id == first[0].id
    assert outbox_events[0].logical_key == first[0].dedup_key
    assert outbox_events[0].payload == {
        "alert_event_id": first[0].id,
        "watchlist_item_id": item.id,
        "product_id": product.id,
        "user_id": item.user_id,
        "target_price_minor": 10_000,
        "observed_price_minor": 9_999,
        "currency": "RUB",
    }


@pytest.mark.parametrize("duplicate_stage", ["alert", "outbox"])
def test_evaluate_product_returns_empty_when_duplicate_race_hits_unique_constraint(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    duplicate_stage: str,
) -> None:
    _, product = _create_watchlist_item(session)
    product.current_price_minor = 9_999
    product.currency = "RUB"
    product.title = "Before race"
    session.flush()

    original_flush = session.flush
    state = {"raised": False}

    def flaky_flush(*args: object, **kwargs: object) -> None:
        if not state["raised"]:
            if duplicate_stage == "alert" and any(
                isinstance(obj, AlertEvent) for obj in session.new
            ):
                state["raised"] = True
                raise IntegrityError("duplicate alert_events.dedup_key", {}, Exception("dup"))
            if duplicate_stage == "outbox" and any(
                isinstance(obj, OutboxEvent) for obj in session.new
            ):
                state["raised"] = True
                raise IntegrityError("duplicate outbox_events.logical_key", {}, Exception("dup"))
        original_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", flaky_flush)

    alerts = NotificationService(session).evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, 2, tzinfo=UTC),
    )

    assert alerts == []
    assert session.scalars(select(AlertEvent)).all() == []
    assert _price_target_outbox_events(session) == []

    product.title = f"Outer commit survives {duplicate_stage}"
    session.commit()
    session.expire_all()

    refreshed = session.get(Product, product.id)
    assert refreshed is not None
    assert refreshed.title == f"Outer commit survives {duplicate_stage}"


def test_evaluate_product_skips_inactive_watchlist_item(session: Session) -> None:
    item, product = _create_watchlist_item(session)
    item.status = "inactive"
    product.current_price_minor = 9_999
    product.currency = "RUB"
    session.flush()

    alerts = NotificationService(session).evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, 3, tzinfo=UTC),
    )

    _assert_no_notifications_created(session, alerts)


def test_evaluate_product_skips_null_target_price(session: Session) -> None:
    item, product = _create_watchlist_item(session)
    item.target_price_minor = None
    product.current_price_minor = 9_999
    product.currency = "RUB"
    session.flush()

    alerts = NotificationService(session).evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, 4, tzinfo=UTC),
    )

    _assert_no_notifications_created(session, alerts)


def test_evaluate_product_skips_null_product_current_price(session: Session) -> None:
    _, product = _create_watchlist_item(session)
    product.current_price_minor = None
    product.currency = "RUB"
    session.flush()

    alerts = NotificationService(session).evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, 5, tzinfo=UTC),
    )

    _assert_no_notifications_created(session, alerts)


def test_evaluate_product_skips_when_price_is_above_target(session: Session) -> None:
    _, product = _create_watchlist_item(session)
    product.current_price_minor = 10_001
    product.currency = "RUB"
    session.flush()

    alerts = NotificationService(session).evaluate_product(
        product_id=product.id,
        now=datetime(2026, 6, 30, 6, tzinfo=UTC),
    )

    _assert_no_notifications_created(session, alerts)


def _create_watchlist_item(
    session: Session,
    *,
    target_price_minor: int | None = 10_000,
) -> tuple[WatchlistItem, Product]:
    SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item",
        target_price_minor=target_price_minor,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    assert result.item is not None
    product = result.item.product
    assert product is not None
    return result.item, product


def _assert_no_notifications_created(
    session: Session,
    alerts: list[AlertEvent],
) -> None:
    assert alerts == []
    assert session.scalars(select(AlertEvent)).all() == []
    assert _price_target_outbox_events(session) == []


def _price_target_outbox_events(session: Session) -> list[OutboxEvent]:
    return session.scalars(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "notification.price_target_reached"
        )
    ).all()
