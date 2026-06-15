from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.monitoring import (
    ImportedCollection,
    ImportedItem,
    MarketplaceConnection,
    MarketplaceSessionSecret,
    MarketplaceSyncSession,
    ProductMatchGroup,
    ProductOffer,
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
    ImportedCollectionResponse,
    ImportedItemResponse,
    ProductCompareResponse,
    ProductOfferResponse,
    SyncItemsRequest,
    SyncItemsResponse,
    SyncSessionCreate,
    SyncSessionFinish,
    SyncSessionResponse,
)
from app.services.marketplace_sessions import record_marketplace_sync_auth_failure

AUTH_FAILURE_REASONS = frozenset({"401", "403", "login_required", "expired"})


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
        imported_item.raw_json = item.raw_json
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
        )
        .order_by(ImportedCollection.id.asc())
    ).all()
    return CollectionsResponse(
        items=[_serialize_collection(collection) for collection in collections]
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


def create_admin_store(
    session: Session,
    request: AdminStoreCreate,
) -> AdminStoreResponse:
    store = session.scalar(select(Store).where(Store.store_code == request.store_code))
    if store is None:
        store = Store(
            store_code=request.store_code,
            display_name=request.display_name,
            enabled=request.enabled,
            homepage_url=request.homepage_url,
        )
        session.add(store)
    else:
        store.display_name = request.display_name
        store.enabled = request.enabled
        store.homepage_url = request.homepage_url
    session.commit()
    session.refresh(store)
    return _serialize_store(store)


def patch_admin_store(
    session: Session,
    store_id: int,
    patch: AdminStorePatch,
) -> AdminStoreResponse | None:
    store = session.get(Store, store_id)
    if store is None:
        return None
    if patch.display_name is not None:
        store.display_name = patch.display_name
    if patch.enabled is not None:
        store.enabled = patch.enabled
    if patch.homepage_url is not None:
        store.homepage_url = patch.homepage_url
    session.commit()
    session.refresh(store)
    return _serialize_store(store)


def list_admin_stores(session: Session) -> AdminStoresResponse:
    stores = session.scalars(
        select(Store).options(selectinload(Store.sources)).order_by(Store.id.asc())
    ).all()
    return AdminStoresResponse(items=[_serialize_store(store) for store in stores])


def create_admin_store_source(
    session: Session,
    store_id: int,
    request: AdminStoreSourceCreate,
) -> AdminStoreSourceResponse | None:
    store = session.get(Store, store_id)
    if store is None:
        return None
    source = session.scalar(
        select(StoreSource).where(
            StoreSource.store_id == store_id,
            StoreSource.source_code == request.source_code,
        )
    )
    display_name = request.display_name or request.source_code
    if source is None:
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
        )
    )
    if collection is None:
        collection = ImportedCollection(
            site_id=site_id,
            external_user_id=external_user_id,
            connection=connection,
            collection_type=collection_type,
            source=connection.marketplace,
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
) -> ImportedCollectionResponse:
    return ImportedCollectionResponse(
        collection_id=collection.id,
        collection_type=collection.collection_type,
        source=collection.source,
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
    return ProductOfferResponse(
        offer_id=offer.id,
        store_code=offer.store.store_code,
        store_display_name=offer.store.display_name,
        source_code=offer.source_code,
        product_url=offer.product_url,
        title=offer.title,
        price=_format_money(offer.price),
        currency=offer.currency,
        availability=offer.availability,
        match_confidence=offer.match_confidence,
        match_label=offer.match_label,
        effective_price=_format_money_or_none(offer.effective_price),
    )


def _serialize_store(store: Store) -> AdminStoreResponse:
    return AdminStoreResponse(
        store_id=store.id,
        store_code=store.store_code,
        display_name=store.display_name,
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
    )


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
