from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.schemas.price_assistant import (
    AdminStoreCreate,
    AdminStorePatch,
    AdminStoreSourceCreate,
)
from app.services.price_assistant import (
    PriceAssistantError,
    create_admin_store,
    create_admin_store_source,
    get_admin_proxy_economics_summary,
    list_admin_fetch_attempts_summary,
    list_admin_matching_diagnostics,
    list_admin_quarantine,
    list_admin_source_health_summary,
    list_admin_stores,
    list_admin_sync_diagnostics,
    patch_admin_store,
    patch_admin_store_source,
)

router = APIRouter(
    prefix="/v1/price-assistant/admin",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/stores")
def get_stores(
    session: DbSession,
    page: int = Query(default=1, ge=1),
    per_page: int | None = Query(default=None, ge=1, le=100),
):
    return list_admin_stores(session, page=page, per_page=per_page)


@router.post("/stores")
def post_store(payload: AdminStoreCreate, request: Request, session: DbSession):
    try:
        return create_admin_store(
            session,
            payload,
            site_id=_request_site_id(request),
        )
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc


@router.patch("/stores/{store_id}")
def patch_store(
    store_id: int,
    payload: AdminStorePatch,
    request: Request,
    session: DbSession,
):
    try:
        result = patch_admin_store(
            session,
            store_id,
            payload,
            site_id=_request_site_id(request),
        )
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="store_not_found")
    return result


@router.post("/stores/{store_id}/sources")
def post_store_source(
    store_id: int,
    payload: AdminStoreSourceCreate,
    request: Request,
    session: DbSession,
):
    try:
        result = create_admin_store_source(
            session,
            store_id,
            payload,
            site_id=_request_site_id(request),
        )
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="store_not_found")
    return result


@router.patch("/stores/{store_id}/sources/{source_id}")
def patch_store_source(
    store_id: int,
    source_id: int,
    payload: AdminStoreSourceCreate,
    request: Request,
    session: DbSession,
):
    try:
        result = patch_admin_store_source(
            session,
            store_id,
            source_id,
            payload,
            site_id=_request_site_id(request),
        )
    except PriceAssistantError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="source_not_found")
    return result


@router.get("/source-health")
def get_source_health(session: DbSession) -> dict[str, list[dict[str, Any]]]:
    return list_admin_source_health_summary(session)


@router.get("/fetch-attempts")
def get_fetch_attempts(session: DbSession) -> dict[str, list[dict[str, Any]]]:
    return list_admin_fetch_attempts_summary(session)


@router.get("/sync-diagnostics")
def get_sync_diagnostics(session: DbSession) -> dict[str, list[dict[str, Any]]]:
    return list_admin_sync_diagnostics(session)


@router.get("/quarantine")
def get_quarantine(session: DbSession) -> dict[str, list[dict[str, Any]]]:
    return list_admin_quarantine(session)


@router.get("/proxy-economics")
def get_proxy_economics(session: DbSession) -> dict[str, Any]:
    return get_admin_proxy_economics_summary(session)


@router.get("/matching-diagnostics")
def get_matching_diagnostics(session: DbSession) -> dict[str, list[dict[str, Any]]]:
    return list_admin_matching_diagnostics(session)


def _request_site_id(request: Request) -> str | None:
    return request.headers.get("X-Savello-Site")
