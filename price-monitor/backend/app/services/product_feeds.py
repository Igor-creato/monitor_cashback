from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.fetchers.base import PriceFetchResult
from app.models.monitoring import ProductFeedItem, ProductFeedSource, TrackedProduct

FEED_ITEM_FRESHNESS_WINDOW = timedelta(hours=6)

_ITEM_FIELDS = (
    "external_product_id",
    "canonical_url",
    "title",
    "image_url",
    "price",
    "old_price",
    "currency",
    "availability",
    "category_id",
    "raw_json",
)

_IN_STOCK_TOKENS = frozenset(
    {
        "in stock",
        "in_stock",
        "instock",
        "available",
        "preorder",
        "1",
        "true",
        "yes",
    }
)


def upsert_feed_items(
    feed_source_id: int,
    items: Iterable[Mapping[str, Any]],
    *,
    session: Session | None = None,
) -> list[ProductFeedItem]:
    with _session_scope(session) as active_session:
        persisted: list[ProductFeedItem] = []
        for item in items:
            canonical_url = item["canonical_url"]
            existing = active_session.scalar(
                select(ProductFeedItem).where(
                    ProductFeedItem.feed_source_id == feed_source_id,
                    ProductFeedItem.canonical_url == canonical_url,
                )
            )
            if existing is None:
                existing = ProductFeedItem(
                    feed_source_id=feed_source_id,
                    canonical_url=canonical_url,
                )
                active_session.add(existing)

            for field in _ITEM_FIELDS:
                if field in item:
                    setattr(existing, field, item[field])

            persisted.append(existing)

        active_session.commit()
        for stored in persisted:
            active_session.refresh(stored)
        return persisted


def find_feed_item_for_product(
    tracked_product: TrackedProduct,
    *,
    session: Session | None = None,
) -> ProductFeedItem | None:
    with _session_scope(session) as active_session:
        external_product_id = tracked_product.external_product_id
        if external_product_id:
            by_external_id = active_session.scalar(
                _enabled_source_query(tracked_product).where(
                    ProductFeedItem.external_product_id == external_product_id
                )
            )
            if by_external_id is not None:
                return by_external_id

        return active_session.scalar(
            _enabled_source_query(tracked_product).where(
                ProductFeedItem.canonical_url == tracked_product.canonical_url
            )
        )


def build_price_result_from_feed_item(feed_item: ProductFeedItem) -> PriceFetchResult:
    return PriceFetchResult(
        product_name=feed_item.title,
        price_current=feed_item.price,
        price_old=feed_item.old_price,
        currency=feed_item.currency,
        availability=_availability_to_bool(feed_item.availability),
        seller_name=None,
        image_url=feed_item.image_url,
        fetched_at=feed_item.updated_at,
    )


def feed_item_is_fresh(
    feed_item: ProductFeedItem,
    *,
    now: datetime | None = None,
    max_age: timedelta = FEED_ITEM_FRESHNESS_WINDOW,
) -> bool:
    reference = _as_utc_naive(now or datetime.now(UTC))
    updated_at = _as_utc_naive(feed_item.updated_at)
    return updated_at >= reference - max_age


def _enabled_source_query(tracked_product: TrackedProduct):
    return (
        select(ProductFeedItem)
        .join(ProductFeedSource, ProductFeedItem.feed_source_id == ProductFeedSource.id)
        .where(
            ProductFeedSource.enabled.is_(True),
            ProductFeedSource.source_code == tracked_product.source,
        )
        .order_by(ProductFeedItem.updated_at.desc(), ProductFeedItem.id.desc())
        .limit(1)
    )


def _availability_to_bool(availability: str | None) -> bool:
    if availability is None:
        return False
    return availability.strip().lower() in _IN_STOCK_TOKENS


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


@contextmanager
def _session_scope(session: Session | None):
    if session is not None:
        yield session
        return

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        yield owned_session
