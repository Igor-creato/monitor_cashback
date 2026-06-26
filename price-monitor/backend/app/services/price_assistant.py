from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, quote, urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.secret_redaction import is_secret_like_key, strip_secret_like_keys
from app.core.url_policy import UrlPolicyError, validate_fetchable_http_url
from app.models.monitoring import (
    SOURCE_EXTRACTION_MODE_VALUES,
    SOURCE_PROXY_TIER_POLICY_VALUES,
    STORE_SOURCE_TYPE_VALUES,
    AuditEvent,
    FetchAttempt,
    ImportedCollection,
    ImportedItem,
    MarketplaceConnection,
    MarketplaceSessionSecret,
    MarketplaceSyncSession,
    ProductFeedItem,
    ProductFeedSource,
    ProductMatchGroup,
    ProductOffer,
    SourceHealthEvent,
    SourceQuarantineState,
    Store,
    StoreSource,
    UserProductSubscription,
)
from app.schemas.price_assistant import (
    AdminDiagnosticsResponse,
    AdminImportResponse,
    AdminImportsResponse,
    AdminStoreCreate,
    AdminStorePatch,
    AdminStoreResponse,
    AdminStoreSourceCreate,
    AdminStoreSourceResponse,
    AdminStoresResponse,
    CollectionsResponse,
    ImportedCollectionDeleteResponse,
    ImportedCollectionResponse,
    ImportedItemResponse,
    ProductCompareResponse,
    ProductOfferResponse,
    ProductSearchItemResponse,
    ProductSearchResponse,
    SyncItemsRequest,
    SyncItemsResponse,
    SyncSessionCreate,
    SyncSessionFinish,
    SyncSessionResponse,
)
from app.services.marketplace_sessions import record_marketplace_sync_auth_failure
from app.services.store_branding import StoreBrand, get_store_brand_map

AUTH_FAILURE_REASONS = frozenset({"401", "403", "login_required", "expired"})

DEFAULT_ADMIN_STORES: tuple[dict[str, str], ...] = (
    {
        "store_code": "ozon",
        "display_name": "Ozon",
        "homepage_url": "https://www.ozon.ru/",
        "search_template": "https://www.ozon.ru/search/?text={query}",
    },
    {
        "store_code": "wildberries",
        "display_name": "Wildberries",
        "homepage_url": "https://www.wildberries.ru/",
        "search_template": "https://www.wildberries.ru/catalog/0/search.aspx?search={query}",
    },
    {
        "store_code": "yandex_market",
        "display_name": "Яндекс Маркет",
        "homepage_url": "https://market.yandex.ru/",
        "search_template": "https://market.yandex.ru/search?text={query}",
    },
)


class PriceAssistantError(ValueError):
    detail: str

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def create_sync_session(
    session: Session,
    request: SyncSessionCreate,
) -> SyncSessionResponse | None:
    connection = session.scalar(
        select(MarketplaceConnection)
        .options(selectinload(MarketplaceConnection.secrets))
        .where(
            MarketplaceConnection.id == request.connection_id,
            MarketplaceConnection.site_id == request.site_id,
            MarketplaceConnection.external_user_id == request.external_user_id,
        )
    )
    if connection is None:
        return None
    if connection.status != "connected" or not _has_active_secret(connection):
        raise PriceAssistantError("session_bundle_unavailable")

    collection = _get_or_create_collection(
        session,
        site_id=request.site_id,
        external_user_id=request.external_user_id,
        connection=connection,
        collection_type=request.collection_type,
    )
    sync_session = MarketplaceSyncSession(
        connection=connection,
        collection=collection,
        site_id=request.site_id,
        external_user_id=request.external_user_id,
        source=connection.marketplace,
        collection_type=request.collection_type,
        status="running",
        started_at=_as_utc_naive(request.started_at),
    )
    session.add(sync_session)
    session.commit()
    session.refresh(sync_session)
    return _serialize_sync_session(sync_session)


def upsert_sync_items(
    session: Session,
    sync_session_id: int,
    request: SyncItemsRequest,
) -> SyncItemsResponse | None:
    sync_session = _get_owner_scoped_sync_session(
        session,
        sync_session_id,
        site_id=request.site_id,
        external_user_id=request.external_user_id,
    )
    if sync_session is None or sync_session.collection is None:
        return None

    now = _as_utc_naive(datetime.now(UTC))
    for item in request.items:
        _validate_product_url(item.product_url)
        imported_item = session.scalar(
            select(ImportedItem).where(
                ImportedItem.collection_id == sync_session.collection_id,
                ImportedItem.external_item_id == item.external_item_id,
            )
        )
        if imported_item is None:
            imported_item = ImportedItem(
                collection=sync_session.collection,
                external_item_id=item.external_item_id,
                product_url=item.product_url,
            )
            session.add(imported_item)
        imported_item.sync_session = sync_session
        imported_item.source_product_id = item.source_product_id
        imported_item.product_url = item.product_url
        imported_item.title = item.title
        imported_item.quantity = item.quantity
        imported_item.raw_json = strip_secret_like_keys(item.raw_json)
        imported_item.last_seen_at = now

    session.flush()
    item_count = _count_collection_items(session, sync_session.collection_id)
    sync_session.item_count = item_count
    sync_session.collection.imported_at = now
    session.commit()
    return SyncItemsResponse(
        sync_session_id=sync_session.id,
        collection_id=sync_session.collection_id,
        upserted_count=len(request.items),
        item_count=item_count,
    )


def finish_sync_session(
    session: Session,
    sync_session_id: int,
    request: SyncSessionFinish,
) -> SyncSessionResponse | None:
    sync_session = _get_owner_scoped_sync_session(
        session,
        sync_session_id,
        site_id=request.site_id,
        external_user_id=request.external_user_id,
    )
    if sync_session is None:
        return None
    if request.status not in {"succeeded", "failed"}:
        raise PriceAssistantError("invalid_sync_status")

    sync_session.status = request.status
    sync_session.reason = request.reason
    sync_session.finished_at = _as_utc_naive(request.finished_at)
    if request.reason in AUTH_FAILURE_REASONS:
        record_marketplace_sync_auth_failure(
            session,
            sync_session.connection_id,
            reason=request.reason,
            now=request.finished_at,
        )
        session.refresh(sync_session)
    else:
        session.commit()
        session.refresh(sync_session)
    return _serialize_sync_session(sync_session)


def list_collections(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
) -> CollectionsResponse:
    collections = session.scalars(
        select(ImportedCollection)
        .options(selectinload(ImportedCollection.items))
        .where(
            ImportedCollection.site_id == site_id,
            ImportedCollection.external_user_id == external_user_id,
            ImportedCollection.status == "active",
        )
        .order_by(ImportedCollection.id.asc())
    ).all()
    brand_by_source = get_store_brand_map(
        session,
        [collection.source for collection in collections],
    )
    return CollectionsResponse(
        items=[
            _serialize_collection(
                collection,
                brand_by_source.get(collection.source),
            )
            for collection in collections
        ]
    )


def archive_imported_collection(
    session: Session,
    *,
    collection_id: int,
    site_id: str,
    external_user_id: str,
) -> ImportedCollectionDeleteResponse | None:
    collection = session.scalar(
        select(ImportedCollection).where(
            ImportedCollection.id == collection_id,
            ImportedCollection.site_id == site_id,
            ImportedCollection.external_user_id == external_user_id,
            ImportedCollection.status == "active",
        )
    )
    if collection is None:
        return None

    collection.status = "archived"
    session.commit()
    session.refresh(collection)
    return ImportedCollectionDeleteResponse(
        collection_id=collection.id,
        status=collection.status,
    )


def compare_product(
    session: Session,
    *,
    tracked_product_id: int,
    site_id: str,
    external_user_id: str,
) -> ProductCompareResponse | None:
    subscription = session.scalar(
        select(UserProductSubscription).where(
            UserProductSubscription.tracked_product_id == tracked_product_id,
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
            UserProductSubscription.is_active.is_(True),
        )
    )
    if subscription is None:
        return None

    offers = session.scalars(
        select(ProductOffer)
        .join(ProductMatchGroup)
        .options(selectinload(ProductOffer.store))
        .where(ProductMatchGroup.tracked_product_id == tracked_product_id)
        .order_by(ProductOffer.price.asc(), ProductOffer.id.asc())
    ).all()
    return ProductCompareResponse(
        tracked_product_id=tracked_product_id,
        offers=[_serialize_offer(offer) for offer in offers],
    )


def search_products(
    session: Session,
    *,
    query: str,
    region_code: str,
    limit: int,
) -> ProductSearchResponse:
    normalized_query = " ".join(query.split())
    enabled_sources = _enabled_store_sources(session)
    items: list[ProductSearchItemResponse] = []

    for source in enabled_sources:
        feed_items = session.scalars(
            select(ProductFeedItem)
            .join(ProductFeedSource)
            .where(
                ProductFeedSource.enabled.is_(True),
                ProductFeedSource.source_code == source.source_code,
                ProductFeedSource.region_code.in_([region_code, "default"]),
            )
            .order_by(ProductFeedItem.updated_at.desc(), ProductFeedItem.id.asc())
        ).all()
        for feed_item in feed_items:
            score = _search_match_score(normalized_query, feed_item)
            if score <= 0:
                continue
            items.append(
                _serialize_search_item(
                    source,
                    feed_item,
                    score=score,
                    query=normalized_query,
                    region_code=region_code,
                )
            )

    items.sort(
        key=lambda item: (
            -(item.match_score or 0),
            item.store_display_name.lower(),
            item.source_code,
            item.title or "",
        )
    )
    return ProductSearchResponse(
        query=normalized_query,
        region_code=region_code,
        items=items[:limit],
        fallbacks=[
            _serialize_search_fallback(source, normalized_query, region_code)
            for source in enabled_sources
            if source.search_template
        ],
    )


def create_admin_store(
    session: Session,
    request: AdminStoreCreate,
    *,
    site_id: str | None = None,
) -> AdminStoreResponse:
    _validate_homepage_url(request.homepage_url)
    logo_url = _normalize_logo_url(request.logo_url)
    _validate_logo_url(logo_url)
    store_code, display_name, homepage_url, domains = _store_identity_from_request(
        request
    )
    store = session.scalar(select(Store).where(Store.store_code == store_code))
    event_type = "price_assistant_store_updated"
    if store is None:
        event_type = "price_assistant_store_created"
        store = Store(
            store_code=store_code,
            display_name=display_name,
            logo_url=logo_url,
            enabled=request.enabled,
            homepage_url=homepage_url,
        )
        session.add(store)
    else:
        store.display_name = display_name
        store.logo_url = logo_url
        store.enabled = request.enabled
        store.homepage_url = homepage_url
    session.flush()
    _ensure_default_store_source(session, store, domains)
    _add_admin_audit_event(
        session,
        event_type=event_type,
        entity_type="store",
        entity_id=str(store.id),
        site_id=site_id,
        metadata={"store_code": store.store_code},
    )
    session.commit()
    session.refresh(store)
    return _serialize_store(store)


def seed_default_admin_stores(session: Session) -> None:
    for item in DEFAULT_ADMIN_STORES:
        request = AdminStoreCreate(
            store_code=item["store_code"],
            display_name=item["display_name"],
            enabled=True,
            homepage_url=item["homepage_url"],
        )
        _validate_homepage_url(request.homepage_url)
        store_code, display_name, homepage_url, domains = _store_identity_from_request(
            request
        )
        store = session.scalar(select(Store).where(Store.store_code == store_code))
        if store is None:
            store = Store(
                store_code=store_code,
                display_name=display_name,
                enabled=True,
                homepage_url=homepage_url,
            )
            session.add(store)
            session.flush()
        else:
            store.display_name = display_name
            store.enabled = True
            store.homepage_url = homepage_url
        _ensure_default_store_source(
            session,
            store,
            domains,
            search_template=item["search_template"],
        )
    session.commit()


def patch_admin_store(
    session: Session,
    store_id: int,
    patch: AdminStorePatch,
    *,
    site_id: str | None = None,
) -> AdminStoreResponse | None:
    store = session.get(Store, store_id)
    if store is None:
        return None
    if patch.display_name is not None:
        display_name = patch.display_name.strip()
        if not display_name:
            raise PriceAssistantError("display_name_required")
        store.display_name = display_name
    if patch.enabled is not None:
        store.enabled = patch.enabled
    if patch.homepage_url is not None:
        _validate_homepage_url(patch.homepage_url)
        store.homepage_url = patch.homepage_url
    if "logo_url" in patch.model_fields_set:
        logo_url = _normalize_logo_url(patch.logo_url)
        _validate_logo_url(logo_url)
        store.logo_url = logo_url
    _add_admin_audit_event(
        session,
        event_type="price_assistant_store_updated",
        entity_type="store",
        entity_id=str(store.id),
        site_id=site_id,
        metadata={"store_code": store.store_code},
    )
    session.commit()
    session.refresh(store)
    return _serialize_store(store)


def list_admin_stores(
    session: Session,
    *,
    page: int = 1,
    per_page: int | None = None,
) -> AdminStoresResponse:
    total_items = session.scalar(select(func.count(Store.id))) or 0
    current_page = max(1, page)
    query = select(Store).options(selectinload(Store.sources)).order_by(Store.id.asc())

    if per_page is not None:
        current_per_page = max(1, min(per_page, 100))
        query = query.limit(current_per_page).offset(
            (current_page - 1) * current_per_page
        )
        total_pages = (total_items + current_per_page - 1) // current_per_page
    else:
        current_per_page = total_items
        total_pages = 1 if total_items > 0 else 0

    stores = session.scalars(query).all()
    return AdminStoresResponse(
        items=[_serialize_store(store) for store in stores],
        total_items=total_items,
        page=current_page,
        per_page=current_per_page,
        total_pages=total_pages,
    )


def create_admin_store_source(
    session: Session,
    store_id: int,
    request: AdminStoreSourceCreate,
    *,
    site_id: str | None = None,
) -> AdminStoreSourceResponse | None:
    store = session.get(Store, store_id)
    if store is None:
        return None
    _validate_admin_source_policy(request)
    source = session.scalar(
        select(StoreSource).where(
            StoreSource.store_id == store_id,
            StoreSource.source_code == request.source_code,
        )
    )
    display_name = request.display_name or request.source_code
    event_type = "price_assistant_source_updated"
    if source is None:
        event_type = "price_assistant_source_created"
        source = StoreSource(
            store=store,
            source_code=request.source_code,
            display_name=display_name,
            enabled=request.enabled,
            source_type=request.source_type,
            metadata_json=request.metadata_json,
        )
        session.add(source)
    else:
        source.display_name = display_name
        source.enabled = request.enabled
        source.source_type = request.source_type
        source.metadata_json = request.metadata_json
    _apply_admin_source_policy(source, request)
    session.flush()
    _add_admin_audit_event(
        session,
        event_type=event_type,
        entity_type="store_source",
        entity_id=str(source.id),
        site_id=site_id,
        metadata={"store_code": store.store_code, "source_code": source.source_code},
    )
    session.commit()
    session.refresh(source)
    return _serialize_store_source(source)


def patch_admin_store_source(
    session: Session,
    store_id: int,
    source_id: int,
    request: AdminStoreSourceCreate,
    *,
    site_id: str | None = None,
) -> AdminStoreSourceResponse | None:
    source = session.scalar(
        select(StoreSource).where(
            StoreSource.id == source_id,
            StoreSource.store_id == store_id,
        )
    )
    if source is None:
        return None
    _validate_admin_source_policy(request)
    source.source_code = request.source_code
    source.display_name = request.display_name or request.source_code
    source.enabled = request.enabled
    source.source_type = request.source_type
    source.metadata_json = request.metadata_json
    _apply_admin_source_policy(source, request)
    session.flush()
    _add_admin_audit_event(
        session,
        event_type="price_assistant_source_updated",
        entity_type="store_source",
        entity_id=str(source.id),
        site_id=site_id,
        metadata={"source_code": source.source_code},
    )
    session.commit()
    session.refresh(source)
    return _serialize_store_source(source)


def list_admin_imports(session: Session) -> AdminImportsResponse:
    collections = session.scalars(
        select(ImportedCollection)
        .options(selectinload(ImportedCollection.items))
        .order_by(ImportedCollection.id.asc())
    ).all()
    return AdminImportsResponse(
        items=[
            AdminImportResponse(
                collection_id=collection.id,
                site_id=collection.site_id,
                external_user_id=collection.external_user_id,
                source=collection.source,
                region_code=collection.region_code,
                collection_type=collection.collection_type,
                status=collection.status,
                item_count=len(collection.items),
            )
            for collection in collections
        ]
    )


def get_admin_diagnostics(session: Session) -> AdminDiagnosticsResponse:
    return AdminDiagnosticsResponse(
        marketplace_connections_total=_count(session, MarketplaceConnection.id),
        encrypted_session_secrets_total=_count(session, MarketplaceSessionSecret.id),
        imported_collections_total=_count(session, ImportedCollection.id),
        imported_items_total=_count(session, ImportedItem.id),
        stores_total=_count(session, Store.id),
        store_sources_total=_count(session, StoreSource.id),
    )


def list_admin_source_health_summary(
    session: Session,
) -> dict[str, list[dict[str, Any]]]:
    events = session.scalars(
        select(SourceHealthEvent).order_by(SourceHealthEvent.id.asc())
    )
    return {
        "items": [
            {
                "source_code": event.source_code,
                "event_type": event.event_type,
                "status_code": event.status_code,
                "response_ms": event.response_ms,
                "created_at": event.created_at,
            }
            for event in events
        ]
    }


def list_admin_fetch_attempts_summary(
    session: Session,
) -> dict[str, list[dict[str, Any]]]:
    attempts = session.scalars(select(FetchAttempt).order_by(FetchAttempt.id.asc()))
    return {
        "items": [
            {
                "attempt_id": attempt.id,
                "tracked_product_id": attempt.tracked_product_id,
                "source_code": attempt.source_code,
                "strategy": attempt.strategy,
                "proxy_pool_id": attempt.proxy_pool_id,
                "proxy_endpoint_id": attempt.proxy_endpoint_id,
                "status": attempt.status,
                "error_type": attempt.error_type,
                "http_status": attempt.http_status,
                "response_ms": attempt.response_ms,
                "cost_estimated": _format_money_or_none(attempt.cost_estimated),
                "created_at": attempt.created_at,
            }
            for attempt in attempts
        ]
    }


def list_admin_sync_diagnostics(session: Session) -> dict[str, list[dict[str, Any]]]:
    sync_sessions = session.scalars(
        select(MarketplaceSyncSession).order_by(MarketplaceSyncSession.id.asc())
    )
    return {
        "items": [
            {
                "sync_session_id": sync_session.id,
                "connection_id": sync_session.connection_id,
                "collection_id": sync_session.collection_id,
                "source": sync_session.source,
                "collection_type": sync_session.collection_type,
                "status": sync_session.status,
                "reason": sync_session.reason,
                "item_count": sync_session.item_count,
                "started_at": sync_session.started_at,
                "finished_at": sync_session.finished_at,
            }
            for sync_session in sync_sessions
        ]
    }


def list_admin_quarantine(session: Session) -> dict[str, list[dict[str, Any]]]:
    states = session.scalars(
        select(SourceQuarantineState).order_by(SourceQuarantineState.id.asc())
    )
    return {
        "items": [
            {
                "source_code": state.source_code,
                "status": state.status,
                "reason": state.reason,
                "error_type": state.error_type,
                "quarantined_until": state.quarantined_until,
                "updated_at": state.updated_at,
            }
            for state in states
        ]
    }


def get_admin_proxy_economics_summary(session: Session) -> dict[str, Any]:
    from app.services.admin import get_admin_fetch_economics

    return get_admin_fetch_economics(session).model_dump(mode="json")


def list_admin_matching_diagnostics(
    session: Session,
) -> dict[str, list[dict[str, Any]]]:
    offers = session.scalars(
        select(ProductOffer)
        .options(
            selectinload(ProductOffer.store),
            selectinload(ProductOffer.match_group),
        )
        .order_by(ProductOffer.id.asc())
    )
    items: list[dict[str, Any]] = []
    for offer in offers:
        metadata = offer.raw_json or {}
        items.append(
            {
                "offer_id": offer.id,
                "store_code": offer.store.store_code,
                "source_code": offer.source_code,
                "external_product_id": offer.external_product_id,
                "region_code": offer.region_code,
                "title": offer.title,
                "price": _format_money(offer.price),
                "currency": offer.currency,
                "match_confidence": offer.match_confidence,
                "match_label": offer.match_label,
                "match_score": metadata.get("match_score"),
                "match_status": metadata.get("match_status"),
                "match_key": offer.match_group.match_key,
            }
        )
    return {"items": items}


def _get_or_create_collection(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    connection: MarketplaceConnection,
    collection_type: str,
) -> ImportedCollection:
    collection = session.scalar(
        select(ImportedCollection).where(
            ImportedCollection.site_id == site_id,
            ImportedCollection.external_user_id == external_user_id,
            ImportedCollection.source == connection.marketplace,
            ImportedCollection.collection_type == collection_type,
            ImportedCollection.region_code == connection.region_code,
        )
    )
    if collection is None:
        collection = ImportedCollection(
            site_id=site_id,
            external_user_id=external_user_id,
            connection=connection,
            collection_type=collection_type,
            source=connection.marketplace,
            region_code=connection.region_code,
            status="active",
        )
        session.add(collection)
        session.flush()
    else:
        collection.connection = connection
        collection.status = "active"
    return collection


def _get_owner_scoped_sync_session(
    session: Session,
    sync_session_id: int,
    *,
    site_id: str,
    external_user_id: str,
) -> MarketplaceSyncSession | None:
    return session.scalar(
        select(MarketplaceSyncSession)
        .options(selectinload(MarketplaceSyncSession.collection))
        .where(
            MarketplaceSyncSession.id == sync_session_id,
            MarketplaceSyncSession.site_id == site_id,
            MarketplaceSyncSession.external_user_id == external_user_id,
        )
    )


def _serialize_sync_session(
    sync_session: MarketplaceSyncSession,
) -> SyncSessionResponse:
    return SyncSessionResponse(
        sync_session_id=sync_session.id,
        connection_id=sync_session.connection_id,
        collection_id=sync_session.collection_id,
        collection_type=sync_session.collection_type,
        source=sync_session.source,
        status=sync_session.status,
        item_count=sync_session.item_count,
        reason=sync_session.reason,
    )


def _serialize_collection(
    collection: ImportedCollection,
    brand: StoreBrand | None = None,
) -> ImportedCollectionResponse:
    return ImportedCollectionResponse(
        collection_id=collection.id,
        collection_type=collection.collection_type,
        source=collection.source,
        source_display_name=brand.display_name if brand is not None else None,
        source_logo_url=brand.logo_url if brand is not None else None,
        region_code=collection.region_code,
        status=collection.status,
        items=[
            ImportedItemResponse(
                item_id=item.id,
                external_item_id=item.external_item_id,
                source_product_id=item.source_product_id,
                product_url=item.product_url,
                title=item.title,
                quantity=item.quantity,
            )
            for item in sorted(collection.items, key=lambda value: value.id)
        ],
    )


def _serialize_offer(offer: ProductOffer) -> ProductOfferResponse:
    match_metadata = offer.raw_json or {}
    return ProductOfferResponse(
        offer_id=offer.id,
        store_code=offer.store.store_code,
        store_display_name=offer.store.display_name,
        store_logo_url=offer.store.logo_url,
        source_code=offer.source_code,
        region_code=offer.region_code,
        product_url=offer.product_url,
        title=offer.title,
        price=_format_money(offer.price),
        currency=offer.currency,
        availability=offer.availability,
        match_confidence=offer.match_confidence,
        match_label=offer.match_label,
        match_score=match_metadata.get("match_score"),
        match_status=match_metadata.get("match_status"),
        match_explanation=match_metadata.get("match_explanation"),
        effective_price=_format_money_or_none(offer.effective_price),
    )


def _serialize_search_item(
    source: StoreSource,
    feed_item: ProductFeedItem,
    *,
    score: int,
    query: str,
    region_code: str,
) -> ProductSearchItemResponse:
    return ProductSearchItemResponse(
        store_code=source.store.store_code,
        store_display_name=source.store.display_name,
        store_logo_url=source.store.logo_url,
        source_code=source.source_code,
        source_display_name=source.display_name,
        source_logo_url=source.store.logo_url,
        title=feed_item.title,
        product_url=feed_item.canonical_url,
        image_url=feed_item.image_url,
        price=_format_money(feed_item.price),
        old_price=_format_money_or_none(feed_item.old_price),
        currency=feed_item.currency,
        availability=feed_item.availability,
        match_label="same_product" if score >= 80 else "analog",
        match_score=score,
        search_url=_build_search_url(source.search_template, query, region_code),
        is_fallback=False,
    )


def _serialize_search_fallback(
    source: StoreSource,
    query: str,
    region_code: str,
) -> ProductSearchItemResponse:
    return ProductSearchItemResponse(
        store_code=source.store.store_code,
        store_display_name=source.store.display_name,
        store_logo_url=source.store.logo_url,
        source_code=source.source_code,
        source_display_name=source.display_name,
        source_logo_url=source.store.logo_url,
        title=None,
        product_url=None,
        image_url=None,
        price=None,
        old_price=None,
        currency=None,
        availability=None,
        match_label="search",
        match_score=None,
        search_url=_build_search_url(source.search_template, query, region_code),
        is_fallback=True,
    )


def _serialize_store(store: Store) -> AdminStoreResponse:
    return AdminStoreResponse(
        store_id=store.id,
        store_code=store.store_code,
        display_name=store.display_name,
        logo_url=store.logo_url,
        enabled=store.enabled,
        homepage_url=store.homepage_url,
        sources=[_serialize_store_source(source) for source in store.sources],
    )


def _serialize_store_source(source: StoreSource) -> AdminStoreSourceResponse:
    return AdminStoreSourceResponse(
        source_id=source.id,
        source_code=source.source_code,
        display_name=source.display_name,
        source_type=source.source_type,
        enabled=source.enabled,
        domains=source.domains_json or [],
        search_template=source.search_template,
        region_support=source.region_support_json or [],
        priority=source.priority,
        extraction_mode=source.extraction_mode,
        proxy_tier_policy=source.proxy_tier_policy,
        min_fetch_interval_minutes=source.min_fetch_interval_minutes,
        matching_threshold=source.matching_threshold,
        cashback_merchant_mapping=source.cashback_merchant_mapping_json,
        metadata_json=source.metadata_json,
    )


def _store_identity_from_request(
    request: AdminStoreCreate,
) -> tuple[str, str, str, list[str]]:
    if request.homepage_url is None:
        raise PriceAssistantError("homepage_url_required")
    parsed = urlparse(request.homepage_url)
    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        raise PriceAssistantError("invalid_url")
    domains = _domains_for_homepage_hostname(hostname)
    store_code = request.store_code or _store_code_from_hostname(hostname)
    display_name = request.display_name.strip()
    if not display_name:
        raise PriceAssistantError("display_name_required")
    return store_code, display_name, request.homepage_url, domains


def _ensure_default_store_source(
    session: Session,
    store: Store,
    domains: list[str],
    *,
    search_template: str | None = None,
) -> StoreSource:
    source_code = f"{store.store_code}-default"
    source = session.scalar(
        select(StoreSource).where(
            StoreSource.store_id == store.id,
            StoreSource.source_code == source_code,
        )
    )
    if source is None:
        source = StoreSource(
            store=store,
            source_code=source_code,
            display_name=store.display_name,
            enabled=store.enabled,
            source_type="api",
        )
        session.add(source)
    source.display_name = store.display_name
    source.enabled = store.enabled
    source.source_type = "api"
    source.domains_json = domains
    source.search_template = search_template
    source.region_support_json = ["default"]
    source.priority = 100
    source.extraction_mode = "hybrid"
    source.proxy_tier_policy = "none"
    source.min_fetch_interval_minutes = 60
    source.matching_threshold = 65
    source.metadata_json = _with_matching_threshold(None, source.matching_threshold)
    return source


def _enabled_store_sources(session: Session) -> list[StoreSource]:
    return list(
        session.scalars(
            select(StoreSource)
            .join(Store)
            .options(selectinload(StoreSource.store))
            .where(
                Store.enabled.is_(True),
                StoreSource.enabled.is_(True),
            )
            .order_by(StoreSource.priority.asc(), StoreSource.id.asc())
        ).all()
    )


def _search_match_score(query: str, feed_item: ProductFeedItem) -> int:
    searchable = " ".join(
        part
        for part in (
            feed_item.title,
            feed_item.external_product_id,
            feed_item.category_id,
        )
        if part
    ).lower()
    tokens = [token.lower() for token in query.split() if token.strip()]
    if not tokens:
        return 0
    if all(token in searchable for token in tokens):
        return 100
    matched = sum(1 for token in tokens if token in searchable)
    if matched == 0:
        return 0
    return round(matched / len(tokens) * 100)


def _build_search_url(
    search_template: str | None,
    query: str,
    region_code: str,
) -> str | None:
    if search_template is None:
        return None
    return (
        search_template.replace("{query}", quote(query, safe=""))
        .replace("{region}", quote(region_code, safe=""))
        .replace("{region_code}", quote(region_code, safe=""))
    )


def _add_admin_audit_event(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    site_id: str | None,
    metadata: dict[str, Any],
) -> None:
    session.add(
        AuditEvent(
            site_id=site_id,
            actor_type="admin",
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata,
        )
    )


def _validate_admin_source_policy(request: AdminStoreSourceCreate) -> None:
    if request.source_type not in STORE_SOURCE_TYPE_VALUES:
        raise PriceAssistantError("invalid_source_type")
    if request.extraction_mode not in SOURCE_EXTRACTION_MODE_VALUES:
        raise PriceAssistantError("invalid_extraction_mode")
    if request.proxy_tier_policy not in SOURCE_PROXY_TIER_POLICY_VALUES:
        raise PriceAssistantError("invalid_proxy_tier_policy")
    domains = _normalize_domains(request.domains)
    _normalize_region_support(request.region_support)
    _validate_search_template(request.search_template, domains)
    _reject_secret_like_mapping(request.cashback_merchant_mapping)
    _reject_secret_like_mapping(request.metadata_json)


def _apply_admin_source_policy(
    source: StoreSource,
    request: AdminStoreSourceCreate,
) -> None:
    matching_threshold = _effective_matching_threshold(request)
    source.domains_json = _normalize_domains(request.domains)
    source.search_template = request.search_template
    source.region_support_json = _normalize_region_support(request.region_support)
    source.priority = request.priority
    source.extraction_mode = request.extraction_mode
    source.proxy_tier_policy = request.proxy_tier_policy
    source.min_fetch_interval_minutes = request.min_fetch_interval_minutes
    source.matching_threshold = matching_threshold
    source.cashback_merchant_mapping_json = request.cashback_merchant_mapping
    source.metadata_json = _with_matching_threshold(
        request.metadata_json,
        matching_threshold,
    )


def _effective_matching_threshold(request: AdminStoreSourceCreate) -> int:
    if "matching_threshold" in request.model_fields_set:
        return request.matching_threshold
    matching = (request.metadata_json or {}).get("matching") or {}
    value = matching.get("min_match_score")
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    return request.matching_threshold


def _with_matching_threshold(
    metadata: dict[str, Any] | None,
    matching_threshold: int,
) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    matching = dict(next_metadata.get("matching") or {})
    matching["min_match_score"] = matching_threshold
    next_metadata["matching"] = matching
    return next_metadata


def _normalize_domains(domains: list[str]) -> list[str]:
    normalized: list[str] = []
    for domain in domains:
        value = domain.strip().lower().rstrip(".")
        if not value or "://" in value or "/" in value or "@" in value:
            raise PriceAssistantError("invalid_domain")
        normalized.append(value)
    return normalized


def _domains_for_homepage_hostname(hostname: str) -> list[str]:
    if hostname.startswith("www."):
        base_hostname = hostname.removeprefix("www.")
        return [base_hostname, hostname]
    return [hostname]


def _store_code_from_hostname(hostname: str) -> str:
    value = hostname.removeprefix("www.")
    code = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not code:
        raise PriceAssistantError("invalid_store_code")
    return code[:64]


def _display_name_from_store_code(store_code: str) -> str:
    return " ".join(part.capitalize() for part in store_code.split("_") if part)


def _normalize_region_support(regions: list[str]) -> list[str]:
    return [region.strip() for region in regions if region.strip()]


def _validate_homepage_url(homepage_url: str | None) -> None:
    if homepage_url is None:
        return
    try:
        validate_fetchable_http_url(homepage_url)
    except UrlPolicyError as exc:
        raise PriceAssistantError("invalid_url") from exc


def _normalize_logo_url(logo_url: str | None) -> str | None:
    if logo_url is None:
        return None
    normalized = logo_url.strip()
    return normalized or None


def _validate_logo_url(logo_url: str | None) -> None:
    if logo_url is None:
        return
    try:
        validate_fetchable_http_url(logo_url)
    except UrlPolicyError as exc:
        raise PriceAssistantError("invalid_logo_url") from exc
    parsed = urlparse(logo_url)
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_secret_like_key(key):
            raise PriceAssistantError("invalid_logo_url")


def _validate_product_url(product_url: str) -> None:
    try:
        validate_fetchable_http_url(product_url)
    except UrlPolicyError as exc:
        raise PriceAssistantError("invalid_product_url") from exc


def _validate_search_template(
    search_template: str | None,
    domains: list[str],
) -> None:
    if search_template is None:
        return
    if not domains:
        raise PriceAssistantError("invalid_search_template")
    try:
        validate_fetchable_http_url(search_template, allowed_domains=domains)
    except UrlPolicyError as exc:
        raise PriceAssistantError("invalid_search_template") from exc
    parsed = urlparse(search_template)
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_secret_like_key(key):
            raise PriceAssistantError("secret_like_policy_value")


def _reject_secret_like_mapping(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_secret_like_key(str(key)):
                raise PriceAssistantError("secret_like_policy_value")
            _reject_secret_like_mapping(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_like_mapping(child)


def _is_secret_like_key(key: str) -> bool:
    return is_secret_like_key(key)


def _count_collection_items(session: Session, collection_id: int | None) -> int:
    if collection_id is None:
        return 0
    return int(
        session.scalar(
            select(func.count(ImportedItem.id)).where(
                ImportedItem.collection_id == collection_id
            )
        )
        or 0
    )


def _count(session: Session, column) -> int:
    return int(session.scalar(select(func.count(column))) or 0)


def _has_active_secret(connection: MarketplaceConnection) -> bool:
    return any(secret.deleted_at is None for secret in connection.secrets)


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"


def _format_money_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _format_money(value)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
