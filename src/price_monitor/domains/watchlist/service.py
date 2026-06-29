from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.core.url_policy import ValidatedProductUrl, validate_public_product_url
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import OutboxEvent
from price_monitor.domains.watchlist.models import WatchlistItem


@dataclass(frozen=True)
class WatchlistAddResult:
    item: WatchlistItem
    created: bool


class WatchlistService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_item(
        self,
        *,
        user_id: str,
        product_url: str,
        target_price_minor: int | None,
        currency: str,
        request_id: str,
    ) -> WatchlistAddResult:
        validated = validate_public_product_url(product_url)
        existing = self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.canonical_url_hash == validated.canonical_url_hash,
            )
        )
        if existing is not None:
            return WatchlistAddResult(item=existing, created=False)

        product = self._get_or_create_product(validated)
        item = WatchlistItem(
            user_id=user_id,
            product=product,
            canonical_url_hash=validated.canonical_url_hash,
            target_price_minor=target_price_minor,
            currency=currency.upper(),
        )
        self._session.add(item)
        self._session.flush()
        self._session.add(
            OutboxEvent(
                event_type="watchlist.item_added",
                aggregate_type="watchlist_item",
                aggregate_id=item.id,
                logical_key=f"watchlist:{item.id}:created",
                request_id=request_id,
                payload={
                    "watchlist_item_id": item.id,
                    "product_id": product.id,
                    "canonical_url": product.canonical_url,
                    "user_id": user_id,
                },
            )
        )
        self._session.flush()
        return WatchlistAddResult(item=item, created=True)

    def delete_item(self, *, item_id: str, request_id: str) -> bool:
        item = self._session.get(WatchlistItem, item_id)
        if item is None or item.status == "deleted":
            return False

        item.status = "deleted"
        item.deleted_at = datetime.now(UTC)
        self._session.add(
            OutboxEvent(
                event_type="watchlist.item_deleted",
                aggregate_type="watchlist_item",
                aggregate_id=item.id,
                logical_key=f"watchlist:{item.id}:deleted",
                request_id=request_id,
                payload={"watchlist_item_id": item.id, "user_id": item.user_id},
            )
        )
        self._session.flush()
        return True

    def _get_or_create_product(self, validated: ValidatedProductUrl) -> Product:
        source_domain = validated.source_domain
        canonical_url_hash = validated.canonical_url_hash
        product = self._session.scalar(
            select(Product).where(
                Product.source_domain == source_domain,
                Product.canonical_url_hash == canonical_url_hash,
            )
        )
        if product is not None:
            return product

        product = Product(
            source_domain=source_domain,
            canonical_url=validated.canonical_url,
            canonical_url_hash=canonical_url_hash,
        )
        self._session.add(product)
        self._session.flush()
        return product
