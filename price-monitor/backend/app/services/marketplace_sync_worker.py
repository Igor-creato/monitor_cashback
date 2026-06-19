from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.monitoring import (
    MarketplaceConnection,
    MarketplaceSessionSource,
    SourceHealthEvent,
    TrackedProduct,
    UserProductSubscription,
)
from app.schemas.price_assistant import (
    ImportedItemInput,
    SyncItemsRequest,
    SyncSessionCreate,
    SyncSessionFinish,
)
from app.services.marketplace_sessions import decrypt_session_bundle_for_sync
from app.services.marketplace_sync_adapters import (
    DEFAULT_ADAPTER_REGISTRY,
    AdapterNotConfigured,
    AdapterRegistry,
    MarketplaceSyncAdapter,
    MarketplaceSyncAdapterResult,
    SanitizedMarketplaceItem,
)
from app.services.price_assistant import (
    create_sync_session,
    finish_sync_session,
    upsert_sync_items,
)
from app.services.source_quarantine import (
    apply_source_quarantine_policy,
    get_effective_source_quarantine_state,
)

logger = logging.getLogger(__name__)

AUTH_FAILURE_REASONS = frozenset({"401", "403", "login_required", "expired"})
RATE_LIMIT_REASONS = frozenset({"429", "rate_limited", "rate_limit"})
BLOCK_REASONS = frozenset({"captcha", "captcha_detected", "blocked", "fingerprint"})
SCOPE_TO_COLLECTION = {
    "cart_read": "cart",
    "favorites_read": "favorites",
}
PROHIBITED_RAW_KEYS = frozenset(
    {"cookie", "cookies", "token", "tokens", "password", "html", "headers"}
)


@dataclass(frozen=True)
class MarketplaceSyncWorkerReport:
    processed_connections: int = 0
    skipped_connections: int = 0
    synced_collections: int = 0
    failed_collections: int = 0
    imported_items: int = 0
    tracked_products_updated: int = 0

    def add(self, other: MarketplaceSyncWorkerReport) -> MarketplaceSyncWorkerReport:
        return MarketplaceSyncWorkerReport(
            processed_connections=self.processed_connections
            + other.processed_connections,
            skipped_connections=self.skipped_connections + other.skipped_connections,
            synced_collections=self.synced_collections + other.synced_collections,
            failed_collections=self.failed_collections + other.failed_collections,
            imported_items=self.imported_items + other.imported_items,
            tracked_products_updated=self.tracked_products_updated
            + other.tracked_products_updated,
        )


def sync_due_marketplace_connections(
    session: Session,
    *,
    adapter_registry: AdapterRegistry | None = None,
    now: datetime | None = None,
    worker_name: str = "marketplace-sync-worker",
    limit: int | None = None,
) -> MarketplaceSyncWorkerReport:
    now_utc = _as_utc_naive(now)
    registry = adapter_registry or DEFAULT_ADAPTER_REGISTRY
    due_connections = _list_due_connections(session, now=now_utc, limit=limit)
    report = MarketplaceSyncWorkerReport()

    for connection in due_connections:
        if not _has_active_secret(connection):
            _mark_retryable(connection, "session_bundle_unavailable", now_utc)
            session.commit()
            report = report.add(MarketplaceSyncWorkerReport(skipped_connections=1))
            continue

        skip_reason = _source_skip_reason(session, connection, now_utc)
        if skip_reason is not None:
            _mark_source_limited(connection, skip_reason, now_utc)
            session.commit()
            report = report.add(MarketplaceSyncWorkerReport(skipped_connections=1))
            continue

        report = report.add(MarketplaceSyncWorkerReport(processed_connections=1))
        try:
            bundle = decrypt_session_bundle_for_sync(
                session,
                connection.id,
                worker_name=worker_name,
                now=now_utc,
            )
        except ValueError:
            _mark_source_limited(connection, "session_bundle_unavailable", now_utc)
            session.commit()
            report = report.add(MarketplaceSyncWorkerReport(failed_collections=1))
            continue

        for collection_type in _collections_for_scope(connection.scope_json):
            if connection.status != "connected":
                break
            adapter = _adapter_for(registry, connection.marketplace, collection_type)
            collection_report = _sync_collection(
                session,
                connection,
                bundle=bundle,
                collection_type=collection_type,
                adapter=adapter,
                now=now_utc,
            )
            report = report.add(collection_report)

        if connection.status == "connected":
            connection.next_retry_at = None
            connection.next_sync_at = _next_sync_at(now_utc)
            session.commit()

    return report


def _sync_collection(
    session: Session,
    connection: MarketplaceConnection,
    *,
    bundle: dict[str, Any],
    collection_type: str,
    adapter: MarketplaceSyncAdapter,
    now: datetime,
) -> MarketplaceSyncWorkerReport:
    sync_session = create_sync_session(
        session,
        SyncSessionCreate(
            site_id=connection.site_id,
            external_user_id=connection.external_user_id,
            connection_id=connection.id,
            collection_type=collection_type,
            started_at=now,
        ),
    )
    if sync_session is None:
        return MarketplaceSyncWorkerReport(failed_collections=1)

    result = adapter.fetch_collection(bundle=bundle, collection_type=collection_type)
    sanitized_items = [_item for _item in result.items if _is_safe_item(_item)]
    imported_count = 0
    tracked_count = 0

    if sanitized_items:
        upsert_sync_items(
            session,
            sync_session.sync_session_id,
            SyncItemsRequest(
                site_id=connection.site_id,
                external_user_id=connection.external_user_id,
                items=[_to_imported_item(item) for item in sanitized_items],
            ),
        )
        imported_count = len(sanitized_items)
        tracked_count = _upsert_tracked_products(
            session,
            connection,
            items=sanitized_items,
            region_code=str(bundle.get("region_hint") or "default"),
            now=now,
        )

    if result.status == "success":
        finish_sync_session(
            session,
            sync_session.sync_session_id,
            SyncSessionFinish(
                site_id=connection.site_id,
                external_user_id=connection.external_user_id,
                status="succeeded",
                reason=None,
                finished_at=now,
            ),
        )
        connection.last_synced_at = now
        session.commit()
        return MarketplaceSyncWorkerReport(
            synced_collections=1,
            imported_items=imported_count,
            tracked_products_updated=tracked_count,
        )

    reason = result.reason or "sync_failed"
    finish_sync_session(
        session,
        sync_session.sync_session_id,
        SyncSessionFinish(
            site_id=connection.site_id,
            external_user_id=connection.external_user_id,
            status="failed",
            reason=reason,
            finished_at=now,
        ),
    )
    _apply_failure_policy(session, connection, reason, result, now)
    return MarketplaceSyncWorkerReport(
        failed_collections=1,
        imported_items=imported_count,
        tracked_products_updated=tracked_count,
    )


def _list_due_connections(
    session: Session,
    *,
    now: datetime,
    limit: int | None,
) -> list[MarketplaceConnection]:
    query = (
        select(MarketplaceConnection)
        .options(selectinload(MarketplaceConnection.secrets))
        .where(
            MarketplaceConnection.status == "connected",
            or_(
                MarketplaceConnection.next_sync_at.is_(None),
                MarketplaceConnection.next_sync_at <= now,
            ),
        )
        .order_by(
            MarketplaceConnection.next_sync_at.asc(), MarketplaceConnection.id.asc()
        )
        .limit(limit or settings.marketplace_sync_due_limit)
    )
    return list(session.scalars(query).all())


def _source_skip_reason(
    session: Session,
    connection: MarketplaceConnection,
    now: datetime,
) -> str | None:
    source = session.scalar(
        select(MarketplaceSessionSource).where(
            MarketplaceSessionSource.marketplace == connection.marketplace
        )
    )
    if source is None or not source.enabled:
        return source.disabled_reason if source is not None else "source_disabled"

    quarantine = get_effective_source_quarantine_state(
        connection.marketplace,
        session=session,
        now=now,
    )
    if quarantine.is_blocked:
        return quarantine.reason or quarantine.error_type or "source_quarantined"
    return None


def _apply_failure_policy(
    session: Session,
    connection: MarketplaceConnection,
    reason: str,
    result: MarketplaceSyncAdapterResult,
    now: datetime,
) -> None:
    if reason in AUTH_FAILURE_REASONS:
        session.refresh(connection)
        return

    if reason in RATE_LIMIT_REASONS:
        _record_source_event(session, connection.marketplace, "http_429", now)
        apply_source_quarantine_policy(
            connection.marketplace,
            "http_429",
            session=session,
            now=now,
        )
        session.refresh(connection)
        retry_after = (
            result.retry_after_seconds or settings.marketplace_sync_rate_limit_seconds
        )
        retry_at = now + timedelta(seconds=retry_after)
        connection.status = "sync_failed_retryable"
        connection.reconnect_reason = reason
        connection.next_retry_at = retry_at
        connection.next_sync_at = retry_at
        session.commit()
        return

    if reason in BLOCK_REASONS:
        _record_source_event(session, connection.marketplace, "captcha_detected", now)
        apply_source_quarantine_policy(
            connection.marketplace,
            "captcha_detected",
            session=session,
            now=now,
        )
        session.refresh(connection)
        _mark_source_limited(connection, "blocked_by_marketplace", now)
        session.commit()
        return

    if reason == "partial_parse":
        session.refresh(connection)
        connection.next_sync_at = _next_sync_at(now)
        session.commit()
        return

    session.refresh(connection)
    _mark_retryable(connection, reason, now)
    session.commit()


def _record_source_event(
    session: Session,
    source_code: str,
    event_type: str,
    now: datetime,
) -> None:
    session.add(
        SourceHealthEvent(
            source_code=source_code,
            event_type=event_type,
            created_at=now,
        )
    )
    session.flush()


def _upsert_tracked_products(
    session: Session,
    connection: MarketplaceConnection,
    *,
    items: list[SanitizedMarketplaceItem],
    region_code: str,
    now: datetime,
) -> int:
    updated = 0
    for item in items:
        if item.source_product_id is None:
            continue
        product = session.scalar(
            select(TrackedProduct).where(
                TrackedProduct.source == connection.marketplace,
                TrackedProduct.external_product_id == item.source_product_id,
                TrackedProduct.region_code == region_code,
                TrackedProduct.variant_hash.is_(None),
            )
        )
        if product is None:
            product = TrackedProduct(
                source=connection.marketplace,
                external_product_id=item.source_product_id,
                canonical_url=item.product_url,
                region_code=region_code,
                variant_hash=None,
                product_name=item.title,
                last_status="synced",
                last_checked_at=now,
                last_success_at=now,
            )
            session.add(product)
            session.flush()
        else:
            product.canonical_url = item.product_url
            product.product_name = item.title
            product.last_status = "synced"
            product.last_checked_at = now
            product.last_success_at = now

        subscription = session.scalar(
            select(UserProductSubscription).where(
                UserProductSubscription.site_id == connection.site_id,
                UserProductSubscription.external_user_id == connection.external_user_id,
                UserProductSubscription.tracked_product_id == product.id,
            )
        )
        if subscription is None:
            session.add(
                UserProductSubscription(
                    site_id=connection.site_id,
                    external_user_id=connection.external_user_id,
                    tracked_product=product,
                    is_active=True,
                )
            )
        else:
            subscription.is_active = True
        updated += 1
    session.commit()
    return updated


def _collections_for_scope(scope: list[str]) -> list[str]:
    collections: list[str] = []
    for scope_name in scope:
        collection_type = SCOPE_TO_COLLECTION.get(scope_name)
        if collection_type is not None and collection_type not in collections:
            collections.append(collection_type)
    return collections


def _adapter_for(
    registry: Mapping[tuple[str, str], MarketplaceSyncAdapter],
    marketplace: str,
    collection_type: str,
) -> MarketplaceSyncAdapter:
    return registry.get((marketplace, collection_type), AdapterNotConfigured())


def _to_imported_item(item: SanitizedMarketplaceItem) -> ImportedItemInput:
    return ImportedItemInput(
        external_item_id=item.external_item_id,
        source_product_id=item.source_product_id,
        product_url=item.product_url,
        title=item.title,
        quantity=item.quantity,
        raw_json=item.raw_json,
    )


def _is_safe_item(item: SanitizedMarketplaceItem) -> bool:
    if item.external_item_id.strip() == "":
        return False
    if item.product_url.strip() == "":
        return False
    if item.quantity < 1:
        return False
    raw_json = item.raw_json or {}
    return not any(key.lower() in PROHIBITED_RAW_KEYS for key in raw_json)


def _has_active_secret(connection: MarketplaceConnection) -> bool:
    return any(secret.deleted_at is None for secret in connection.secrets)


def _mark_source_limited(
    connection: MarketplaceConnection,
    reason: str,
    now: datetime,
) -> None:
    connection.status = "source_limited"
    connection.reconnect_reason = reason
    connection.kill_switch_blocked_at = now
    connection.next_retry_at = None
    connection.next_sync_at = None


def _mark_retryable(
    connection: MarketplaceConnection,
    reason: str,
    now: datetime,
) -> None:
    retry_at = now + timedelta(seconds=settings.marketplace_sync_rate_limit_seconds)
    connection.status = "sync_failed_retryable"
    connection.reconnect_reason = reason
    connection.next_retry_at = retry_at
    connection.next_sync_at = retry_at


def _next_sync_at(now: datetime) -> datetime:
    return now + timedelta(seconds=settings.marketplace_sync_interval_seconds)


def _as_utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
