from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.reliability.models import OutboxEvent
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.domains.watchlist.service import WatchlistService


def test_add_watchlist_item_creates_product_item_and_outbox_event(session: Session) -> None:
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
    assert second.item.id == first.item.id
    assert len(session.scalars(select(WatchlistItem)).all()) == 1
    assert len(session.scalars(select(OutboxEvent)).all()) == 1
