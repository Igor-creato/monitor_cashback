from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session, verify_wordpress_request
from price_monitor.core.idempotency import (
    IdempotencyReplay,
    complete_idempotency_record,
    get_replay_or_reserve,
)
from price_monitor.core.security import VerifiedRequest
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.domains.watchlist.service import WatchlistService

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class WatchlistCreateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    target_price_minor: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)


class WatchlistItemResponse(BaseModel):
    id: str
    user_id: str
    product_id: str
    canonical_url: str
    target_price_minor: int | None
    currency: str
    status: str


class WatchlistCreateResponse(BaseModel):
    created: bool
    item: WatchlistItemResponse


def _serialize_item(item: WatchlistItem) -> WatchlistItemResponse:
    return WatchlistItemResponse(
        id=item.id,
        user_id=item.user_id,
        product_id=item.product_id,
        canonical_url=item.product.canonical_url,
        target_price_minor=item.target_price_minor,
        currency=item.currency,
        status=item.status,
    )


@router.post("/items", response_model=WatchlistCreateResponse)
def create_watchlist_item(
    payload: WatchlistCreateRequest,
    response: Response,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse | WatchlistCreateResponse:
    if not idempotency_key:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {"code": "idempotency_key_required", "message": "Idempotency-Key required"}
            },
        )

    route = "POST /api/v1/watchlist/items"
    reserved = get_replay_or_reserve(
        session=session,
        key=idempotency_key,
        route=route,
        request_hash=verified.body_sha256,
    )
    if isinstance(reserved, IdempotencyReplay):
        return JSONResponse(status_code=reserved.status_code, content=reserved.response_body)

    result = WatchlistService(session).add_item(
        user_id=payload.user_id,
        product_url=payload.url,
        target_price_minor=payload.target_price_minor,
        currency=payload.currency,
        request_id=verified.request_id,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    response_body = WatchlistCreateResponse(
        created=result.created, item=_serialize_item(result.item)
    )
    response_dict = response_body.model_dump()
    complete_idempotency_record(
        record=reserved,
        status_code=response.status_code,
        response_body=_json_ready(response_dict),
    )
    session.commit()
    return response_body


@router.get("/items")
def list_watchlist_items(
    session: Annotated[Session, Depends(get_db_session)],
    user_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    statement = select(WatchlistItem).where(WatchlistItem.status == "active")
    if user_id is not None:
        statement = statement.where(WatchlistItem.user_id == user_id)
    items = session.scalars(statement.order_by(WatchlistItem.created_at.desc())).all()
    return {"items": [_serialize_item(item).model_dump() for item in items]}


@router.delete("/items/{item_id}", response_model=None)
def delete_watchlist_item(
    item_id: str,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response | JSONResponse:
    if not idempotency_key:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {"code": "idempotency_key_required", "message": "Idempotency-Key required"}
            },
        )
    WatchlistService(session).delete_item(item_id=item_id, request_id=verified.request_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _json_ready(value: dict[str, Any]) -> dict[str, Any]:
    return value
