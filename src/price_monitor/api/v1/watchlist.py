from __future__ import annotations

from hashlib import sha256
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
from price_monitor.domains.sources.service import SourceService
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.domains.watchlist.service import WatchlistService

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class WatchlistCreateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    target_price_minor: int | None = Field(default=None)
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
        max_tracked_products=_max_tracked_products(session),
    )
    if result.error_code is not None:
        status_code = _status_for_watchlist_error(result.error_code)
        response_body = _watchlist_error(result.error_code)
        complete_idempotency_record(
            record=reserved,
            status_code=status_code,
            response_body=response_body,
        )
        session.commit()
        return JSONResponse(status_code=status_code, content=response_body)

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
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
    user_id: str,
) -> dict[str, list[dict[str, Any]]]:
    del verified
    statement = select(WatchlistItem).where(WatchlistItem.status == "active")
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

    route = "DELETE /api/v1/watchlist/items"
    reserved = get_replay_or_reserve(
        session=session,
        key=idempotency_key,
        route=route,
        request_hash=_delete_request_hash(item_id=item_id, body_sha256=verified.body_sha256),
    )
    if isinstance(reserved, IdempotencyReplay):
        if reserved.status_code == status.HTTP_204_NO_CONTENT and reserved.response_body == {}:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return JSONResponse(status_code=reserved.status_code, content=reserved.response_body)

    WatchlistService(session).delete_item(item_id=item_id, request_id=verified.request_id)
    complete_idempotency_record(
        record=reserved,
        status_code=status.HTTP_204_NO_CONTENT,
        response_body={},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _json_ready(value: dict[str, Any]) -> dict[str, Any]:
    return value

def _delete_request_hash(*, item_id: str, body_sha256: str) -> str:
    return sha256(f"{item_id}:{body_sha256}".encode()).hexdigest()


def _max_tracked_products(session: Session) -> int:
    settings = SourceService(session).get_settings()
    return int(settings["max_tracked_products_per_user"])


def _status_for_watchlist_error(error_code: str) -> int:
    if error_code in {"duplicate_watchlist_item", "limit_exceeded"}:
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def _watchlist_error(error_code: str) -> dict[str, dict[str, str]]:
    messages = {
        "duplicate_watchlist_item": "Товар уже в списке отслеживания",
        "invalid_target_price": "Некорректная целевая цена",
        "limit_exceeded": "Достигнут лимит отслеживаемых товаров",
        "unsupported_store": "Магазин не поддерживается",
    }
    return {"error": {"code": error_code, "message": messages[error_code]}}
