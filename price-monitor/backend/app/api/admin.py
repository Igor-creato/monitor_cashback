from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.admin_auth import verify_admin_api_key
from app.db import get_db
from app.schemas.admin import (
    AdminErrorsResponse,
    AdminFetchAttemptsResponse,
    AdminFetchEconomicsResponse,
    AdminJobsResponse,
    AdminMarketplaceConnectionsResponse,
    AdminOverviewResponse,
    AdminProductResponse,
    AdminProductsResponse,
    AdminProxyPoolDetailResponse,
    AdminProxyPoolsResponse,
    AdminSourceHealthResponse,
    AdminSourcePatch,
    AdminSourceResponse,
    AdminSourcesResponse,
)
from app.schemas.price_assistant import (
    AdminDiagnosticsResponse,
    AdminImportsResponse,
    AdminStoreCreate,
    AdminStorePatch,
    AdminStoreResponse,
    AdminStoreSourceCreate,
    AdminStoreSourceResponse,
    AdminStoresResponse,
)
from app.services.admin import (
    get_admin_fetch_economics,
    get_admin_overview,
    get_admin_product,
    get_admin_proxy_pool,
    get_admin_source_health,
    list_admin_errors,
    list_admin_fetch_attempts,
    list_admin_jobs,
    list_admin_marketplace_connections,
    list_admin_products,
    list_admin_proxy_pools,
    list_admin_sources,
    patch_admin_source,
)
from app.services.price_assistant import (
    PriceAssistantError,
    create_admin_store,
    create_admin_store_source,
    get_admin_diagnostics,
    list_admin_imports,
    list_admin_stores,
    patch_admin_store,
)

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(verify_admin_api_key)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/overview", response_model=AdminOverviewResponse)
def admin_overview(session: DbSession) -> AdminOverviewResponse:
    return get_admin_overview(session)


@router.get("/sources", response_model=AdminSourcesResponse)
def admin_sources(session: DbSession) -> AdminSourcesResponse:
    return AdminSourcesResponse(items=list_admin_sources(session))


@router.get("/sources/{source_code}/health", response_model=AdminSourceHealthResponse)
def admin_source_health(
    source_code: str,
    session: DbSession,
) -> AdminSourceHealthResponse:
    return get_admin_source_health(session, source_code)


@router.patch("/sources/{source_code}", response_model=AdminSourceResponse)
def admin_patch_source(
    source_code: str,
    patch: AdminSourcePatch,
    session: DbSession,
) -> AdminSourceResponse:
    source = patch_admin_source(session, source_code, patch)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source


@router.get("/products", response_model=AdminProductsResponse)
def admin_products(session: DbSession) -> AdminProductsResponse:
    return AdminProductsResponse(items=list_admin_products(session))


@router.get("/products/{tracked_product_id}", response_model=AdminProductResponse)
def admin_product(
    tracked_product_id: int,
    session: DbSession,
) -> AdminProductResponse:
    product = get_admin_product(session, tracked_product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.get("/jobs", response_model=AdminJobsResponse)
def admin_jobs(session: DbSession) -> AdminJobsResponse:
    return AdminJobsResponse(items=list_admin_jobs(session))


@router.get("/errors", response_model=AdminErrorsResponse)
def admin_errors(session: DbSession) -> AdminErrorsResponse:
    return AdminErrorsResponse(items=list_admin_errors(session))


@router.get("/fetch-economics", response_model=AdminFetchEconomicsResponse)
def admin_fetch_economics(session: DbSession) -> AdminFetchEconomicsResponse:
    return get_admin_fetch_economics(session)


@router.get("/proxy-pools", response_model=AdminProxyPoolsResponse)
def admin_proxy_pools(session: DbSession) -> AdminProxyPoolsResponse:
    return AdminProxyPoolsResponse(items=list_admin_proxy_pools(session))


@router.get("/proxy-pools/{pool_id}", response_model=AdminProxyPoolDetailResponse)
def admin_proxy_pool(
    pool_id: int,
    session: DbSession,
) -> AdminProxyPoolDetailResponse:
    pool = get_admin_proxy_pool(session, pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Proxy pool not found.")
    return pool


@router.get("/fetch-attempts", response_model=AdminFetchAttemptsResponse)
def admin_fetch_attempts(
    session: DbSession,
    source: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
) -> AdminFetchAttemptsResponse:
    return AdminFetchAttemptsResponse(
        items=list_admin_fetch_attempts(
            session,
            source=source,
            strategy=strategy,
            status=status,
        )
    )


@router.get(
    "/marketplace-connections",
    response_model=AdminMarketplaceConnectionsResponse,
)
def admin_marketplace_connections(
    session: DbSession,
) -> AdminMarketplaceConnectionsResponse:
    return list_admin_marketplace_connections(session)


@router.get("/stores", response_model=AdminStoresResponse)
def admin_stores(session: DbSession) -> AdminStoresResponse:
    return list_admin_stores(session)


@router.post("/stores", response_model=AdminStoreResponse)
def admin_create_store(
    payload: AdminStoreCreate,
    session: DbSession,
) -> AdminStoreResponse:
    try:
        return create_admin_store(session, payload)
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc


@router.patch("/stores/{store_id}", response_model=AdminStoreResponse)
def admin_patch_store(
    store_id: int,
    payload: AdminStorePatch,
    session: DbSession,
) -> AdminStoreResponse:
    try:
        store = patch_admin_store(session, store_id, payload)
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found.")
    return store


@router.post(
    "/stores/{store_id}/sources",
    response_model=AdminStoreSourceResponse,
)
def admin_create_store_source(
    store_id: int,
    payload: AdminStoreSourceCreate,
    session: DbSession,
) -> AdminStoreSourceResponse:
    try:
        source = create_admin_store_source(session, store_id, payload)
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    if source is None:
        raise HTTPException(status_code=404, detail="Store not found.")
    return source


@router.get("/imports", response_model=AdminImportsResponse)
def admin_imports(session: DbSession) -> AdminImportsResponse:
    return list_admin_imports(session)


@router.get("/diagnostics", response_model=AdminDiagnosticsResponse)
def admin_diagnostics(session: DbSession) -> AdminDiagnosticsResponse:
    return get_admin_diagnostics(session)
