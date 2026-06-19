"""Import product feed fixtures into ``product_feed_items``.

The importer turns parsed feed records into validated item payloads and
persists them through the existing :func:`app.services.product_feeds.upsert_feed_items`
service (which upserts by ``(feed_source_id, canonical_url)``).

Item-level failures (bad price, missing url) are collected as
:class:`FeedItemError` and do **not** abort the whole import. No HTTP is
performed here: callers pass raw content or a local file path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.feeds.parsers import parse_feed
from app.models.monitoring import ProductFeedItem, ProductFeedSource
from app.services.product_feeds import upsert_feed_items
from app.services.product_matching import materialize_feed_matches

__all__ = [
    "FeedItemError",
    "FeedImportResult",
    "import_feed_content",
    "import_feed_file",
]

_DEFAULT_AVAILABILITY = "out of stock"


@dataclass(frozen=True)
class FeedItemError:
    """A single record that could not be imported."""

    index: int
    reason: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class FeedImportResult:
    """Outcome of a feed import: persisted items plus item-level errors."""

    persisted: list[ProductFeedItem] = field(default_factory=list)
    errors: list[FeedItemError] = field(default_factory=list)

    @property
    def imported_count(self) -> int:
        return len(self.persisted)

    @property
    def error_count(self) -> int:
        return len(self.errors)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_price(value: Any) -> Decimal:
    text = _clean(value)
    if text is None:
        raise ValueError("price is required")
    try:
        price = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid price: {value!r}") from exc
    if price <= 0:
        raise ValueError(f"price must be positive: {value!r}")
    return price


def _to_optional_price(value: Any) -> Decimal | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid old_price: {value!r}") from exc


def _build_item(
    record: Mapping[str, Any],
    feed_source: ProductFeedSource,
) -> dict[str, Any]:
    canonical_url = _clean(record.get("url"))
    if canonical_url is None:
        raise ValueError("url is required")

    item: dict[str, Any] = {
        "canonical_url": canonical_url,
        "external_product_id": _clean(record.get("product_id")),
        "title": _clean(record.get("title")),
        "image_url": _clean(record.get("image_url")),
        "price": _to_price(record.get("price")),
        "old_price": _to_optional_price(record.get("old_price")),
        "currency": _clean(record.get("currency")) or feed_source.currency,
        "availability": _clean(record.get("availability")) or _DEFAULT_AVAILABILITY,
        "category_id": _clean(record.get("category_id")),
        "raw_json": dict(record),
    }
    return item


def import_feed_content(
    session: Session,
    feed_source: ProductFeedSource,
    content: str | bytes,
    *,
    fmt: str | None = None,
) -> FeedImportResult:
    resolved_fmt = fmt or feed_source.format
    fields_mapping = feed_source.fields_mapping_json

    records = parse_feed(content, resolved_fmt, fields_mapping=fields_mapping)

    valid_items: list[dict[str, Any]] = []
    errors: list[FeedItemError] = []
    for index, record in enumerate(records):
        try:
            valid_items.append(_build_item(record, feed_source))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(FeedItemError(index=index, reason=str(exc), raw=dict(record)))

    persisted: list[ProductFeedItem] = []
    if valid_items:
        persisted = upsert_feed_items(feed_source.id, valid_items, session=session)
        materialize_feed_matches(session, feed_source, persisted)
        session.commit()

    return FeedImportResult(persisted=persisted, errors=errors)


def import_feed_file(
    session: Session,
    feed_source: ProductFeedSource,
    path: str | Path,
    *,
    fmt: str | None = None,
) -> FeedImportResult:
    content = Path(path).read_bytes()
    return import_feed_content(session, feed_source, content, fmt=fmt)
