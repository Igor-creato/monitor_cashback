from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from price_monitor.core.url_policy import ValidatedProductUrl, validate_public_product_url
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import OutboxEvent
from price_monitor.domains.sources.service import SourceService
from price_monitor.domains.watchlist.models import WatchlistItem


@dataclass(frozen=True)
class WatchlistAddResult:
    item: WatchlistItem | None
    created: bool
    error_code: str | None = None


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
        max_tracked_products: int = 10,
    ) -> WatchlistAddResult:
        if target_price_minor is not None and target_price_minor < 0:
            return WatchlistAddResult(item=None, created=False, error_code="invalid_target_price")

        source = SourceService(self._session).find_supported_source(product_url)
        if source is None:
            return WatchlistAddResult(item=None, created=False, error_code="unsupported_store")

        validated = validate_public_product_url(product_url)
        active_identity_key = self._build_active_identity_key(
            user_id=user_id, canonical_url_hash=validated.canonical_url_hash
        )
        existing = self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.active_identity_key == active_identity_key,
            )
        )
        if existing is not None:
            return WatchlistAddResult(
                item=existing, created=False, error_code="duplicate_watchlist_item"
            )

        active_count = self._session.scalar(
            select(func.count())
            .select_from(WatchlistItem)
            .where(WatchlistItem.user_id == user_id, WatchlistItem.status == "active")
        )
        if active_count is not None and active_count >= max_tracked_products:
            return WatchlistAddResult(item=None, created=False, error_code="limit_exceeded")

        product = self._get_or_create_product(validated, matched_source_domain=source.source_domain)
        now = datetime.now(UTC)
        item = WatchlistItem(
            user_id=user_id,
            product=product,
            canonical_url_hash=validated.canonical_url_hash,
            active_identity_key=active_identity_key,
            target_price_minor=target_price_minor,
            currency=currency.upper(),
            updated_at=now,
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
        item.updated_at = item.deleted_at
        item.active_identity_key = None
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

    def update_target_price(
        self,
        *,
        item_id: str,
        user_id: str,
        target_price_minor: int | None,
        request_id: str,
    ) -> WatchlistItem:
        del request_id
        if target_price_minor is not None and target_price_minor < 0:
            raise ValueError("invalid_target_price")

        item = self._session.get(WatchlistItem, item_id)
        if item is None or item.user_id != user_id or item.status != "active":
            raise LookupError(item_id)

        item.target_price_minor = target_price_minor
        item.updated_at = datetime.now(UTC)
        self._session.flush()
        return item

    def _get_or_create_product(
        self, validated: ValidatedProductUrl, *, matched_source_domain: str
    ) -> Product:
        source_domain = matched_source_domain
        canonical_url_hash = validated.canonical_url_hash
        product = self._session.scalar(
            select(Product).where(
                Product.source_domain == source_domain,
                Product.canonical_url_hash == canonical_url_hash,
            )
        )
        if product is not None:
            return product

        now = datetime.now(UTC)
        product = Product(
            source_domain=source_domain,
            canonical_url=validated.canonical_url,
            canonical_url_hash=canonical_url_hash,
            updated_at=now,
        )
        self._session.add(product)
        self._session.flush()
        return product

    @staticmethod
    def _build_active_identity_key(*, user_id: str, canonical_url_hash: str) -> str:
        return f"{user_id}:{canonical_url_hash}"
