from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.notifications.service import NotificationService
from price_monitor.domains.reliability.models import AlertEvent, OutboxEvent
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.service import WatchlistService


def test_price_target_alert_created_once_per_threshold_crossing(session: Session) -> None:
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
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    assert result.item is not None
    product = result.item.product
    assert product is not None
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
    assert first[0].dedup_key == f"price-target:{result.item.id}:10000:9999"
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
        "watchlist_item_id": result.item.id,
        "product_id": product.id,
        "user_id": result.item.user_id,
        "target_price_minor": 10_000,
        "observed_price_minor": 9_999,
        "currency": "RUB",
    }
