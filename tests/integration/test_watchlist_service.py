from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.reliability.models import OutboxEvent
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.domains.watchlist.service import WatchlistService


def test_add_watchlist_item_creates_product_item_and_outbox_event(session: Session) -> None:
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
        user_id="wp-user-1",
        product_url="https://example.com/product?id=42&utm_source=ad",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-1",
    )

    assert result.created is True
    assert result.item.product.canonical_url == "https://example.com/product?id=42"
    assert result.item.target_price_minor == 10_000

    events = session.scalars(select(OutboxEvent)).all()
    assert len(events) == 1
    assert events[0].event_type == "watchlist.item_added"
    assert events[0].logical_key == f"watchlist:{result.item.id}:created"


def test_add_watchlist_item_deduplicates_same_user_and_canonical_url(session: Session) -> None:
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
    service = WatchlistService(session)

    first = service.add_item(
        user_id="wp-user-1",
        product_url="https://example.com/product?id=42&utm_source=ad",
        target_price_minor=None,
        currency="RUB",
        request_id="req-1",
    )
    second = service.add_item(
        user_id="wp-user-1",
        product_url="https://EXAMPLE.com:443/product?id=42#section",
        target_price_minor=None,
        currency="RUB",
        request_id="req-2",
    )

    assert first.created is True
    assert second.created is False
    assert second.error_code == "duplicate_watchlist_item"
    assert len(session.scalars(select(WatchlistItem)).all()) == 1
    assert len(session.scalars(select(OutboxEvent)).all()) == 1


def test_add_watchlist_item_rejects_unsupported_source(session: Session) -> None:
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://unsupported.test/item",
        target_price_minor=None,
        currency="RUB",
        request_id="req-unsupported",
        max_tracked_products=10,
    )

    assert result.error_code == "unsupported_store"


def test_active_duplicate_returns_error_but_deleted_item_can_be_readded(session: Session) -> None:
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
    service = WatchlistService(session)
    first = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42",
        target_price_minor=None,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    duplicate = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42&utm_source=ad",
        target_price_minor=None,
        currency="RUB",
        request_id="req-2",
        max_tracked_products=10,
    )

    assert first.created is True
    assert duplicate.error_code == "duplicate_watchlist_item"

    service.delete_item(item_id=first.item.id, request_id="req-3")
    readded = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42",
        target_price_minor=9000,
        currency="RUB",
        request_id="req-4",
        max_tracked_products=10,
    )

    assert readded.created is True
    assert readded.item.id != first.item.id


def test_max_tracked_products_limit_is_enforced(session: Session) -> None:
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
    service = WatchlistService(session)
    first = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/a",
        target_price_minor=None,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=1,
    )
    second = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/b",
        target_price_minor=None,
        currency="RUB",
        request_id="req-2",
        max_tracked_products=1,
    )

    assert first.created is True
    assert second.error_code == "limit_exceeded"
