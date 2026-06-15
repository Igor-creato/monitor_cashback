from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.schemas.price_assistant import (
    CollectionsResponse,
    ProductCompareResponse,
    SyncItemsRequest,
    SyncItemsResponse,
    SyncSessionCreate,
    SyncSessionFinish,
    SyncSessionResponse,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyKeyMissingError,
    require_idempotency_key,
    run_idempotent,
)
from app.services.price_assistant import (
    PriceAssistantError,
    compare_product,
    create_sync_session,
    finish_sync_session,
    list_collections,
    upsert_sync_items,
)

router = APIRouter(dependencies=[Depends(verify_incoming_hmac_request)])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/v1/sync-sessions", response_model=SyncSessionResponse)
async def post_sync_session(
    payload: SyncSessionCreate,
    request: Request,
    session: DbSession,
):
    _verify_site_matches_request(request, payload.site_id)
    idempotency_key = _idempotency_key_or_http(request)
    raw_body = await request.body()

    def operation():
        try:
            result = create_sync_session(session, payload)
        except PriceAssistantError as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        if result is None:
            raise HTTPException(
                status_code=404, detail="Marketplace connection not found."
            )
        return result

    return _run_idempotent_or_http(
        session,
        scope="sync-sessions:create",
        idempotency_key=idempotency_key,
        raw_body=raw_body,
        operation=operation,
    )


@router.post("/v1/sync-sessions/{sync_session_id}/items")
async def post_sync_session_items(
    sync_session_id: int,
    payload: SyncItemsRequest,
    request: Request,
    session: DbSession,
) -> SyncItemsResponse:
    _verify_site_matches_request(request, payload.site_id)
    idempotency_key = _idempotency_key_or_http(request)
    raw_body = await request.body()

    def operation():
        result = upsert_sync_items(session, sync_session_id, payload)
        if result is None:
            raise HTTPException(status_code=404, detail="Sync session not found.")
        return result

    return _run_idempotent_or_http(
        session,
        scope=f"sync-sessions:{sync_session_id}:items",
        idempotency_key=idempotency_key,
        raw_body=raw_body,
        operation=operation,
    )


@router.post("/v1/sync-sessions/{sync_session_id}/finish")
async def post_sync_session_finish(
    sync_session_id: int,
    payload: SyncSessionFinish,
    request: Request,
    session: DbSession,
) -> SyncSessionResponse:
    _verify_site_matches_request(request, payload.site_id)
    idempotency_key = _idempotency_key_or_http(request)
    raw_body = await request.body()

    def operation():
        try:
            result = finish_sync_session(session, sync_session_id, payload)
        except PriceAssistantError as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Sync session not found.")
        return result

    return _run_idempotent_or_http(
        session,
        scope=f"sync-sessions:{sync_session_id}:finish",
        idempotency_key=idempotency_key,
        raw_body=raw_body,
        operation=operation,
    )


@router.get("/v1/collections", response_model=CollectionsResponse)
def get_collections(
    request: Request,
    session: DbSession,
    site_id: Annotated[str, Query(min_length=1, max_length=191)],
    external_user_id: Annotated[str, Query(min_length=1, max_length=191)],
) -> CollectionsResponse:
    _verify_site_matches_request(request, site_id)
    return list_collections(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
    )


@router.get("/v1/products/{tracked_product_id}/compare")
def get_product_compare(
    tracked_product_id: int,
    request: Request,
    session: DbSession,
    site_id: Annotated[str, Query(min_length=1, max_length=191)],
    external_user_id: Annotated[str, Query(min_length=1, max_length=191)],
) -> ProductCompareResponse:
    _verify_site_matches_request(request, site_id)
    result = compare_product(
        session,
        tracked_product_id=tracked_product_id,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Product comparison not found.")
    return result


def _verify_site_matches_request(request: Request, site_id: str) -> None:
    if request.headers.get("X-Savello-Site", "").strip() != site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")


def _idempotency_key_or_http(request: Request) -> str:
    try:
        return require_idempotency_key(request.headers.get("Idempotency-Key"))
    except IdempotencyKeyMissingError as exc:
        raise HTTPException(status_code=400, detail="idempotency_key_required") from exc


def _run_idempotent_or_http(session, **kwargs):
    try:
        return run_idempotent(session, **kwargs)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail="idempotency_key_conflict") from exc
