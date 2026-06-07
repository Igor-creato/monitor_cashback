from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.models.monitoring import UserProductSubscription
from app.schemas.watchlist import (
    WatchlistItemCreate,
    WatchlistItemPatch,
    WatchlistItemResponse,
    WatchlistItemsResponse,
)
from app.services.watchlist import (
    UnsupportedWatchlistSourceError,
    add_watchlist_item,
    delete_watchlist_item,
    list_watchlist_items,
    patch_watchlist_item,
)

router = APIRouter(
    prefix="/v1/watchlist",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/items", response_model=WatchlistItemResponse)
def create_watchlist_item(
    item: WatchlistItemCreate,
    request: Request,
    session: DbSession,
) -> WatchlistItemResponse:
    _verify_site_matches_request(request, item.site_id)
    try:
        subscription = add_watchlist_item(session, item)
    except UnsupportedWatchlistSourceError as exc:
        raise HTTPException(
            status_code=400,
            detail="Unsupported product URL source.",
        ) from exc

    return _serialize_subscription(subscription)


@router.get("/items", response_model=WatchlistItemsResponse)
def get_watchlist_items(
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
    active_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WatchlistItemsResponse:
    _verify_site_matches_request(request, site_id)
    subscriptions = list_watchlist_items(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
        active_only=active_only,
        limit=limit,
    )
    return WatchlistItemsResponse(
        items=[_serialize_subscription(subscription) for subscription in subscriptions],
        limit=limit,
    )


@router.patch("/items/{subscription_id}", response_model=WatchlistItemResponse)
def update_watchlist_item(
    subscription_id: int,
    patch: WatchlistItemPatch,
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
) -> WatchlistItemResponse:
    _verify_site_matches_request(request, site_id)
    subscription = patch_watchlist_item(
        session,
        subscription_id=subscription_id,
        site_id=site_id,
        external_user_id=external_user_id,
        patch=patch,
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")

    return _serialize_subscription(subscription)


@router.delete("/items/{subscription_id}", response_model=WatchlistItemResponse)
def remove_watchlist_item(
    subscription_id: int,
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
) -> WatchlistItemResponse:
    _verify_site_matches_request(request, site_id)
    subscription = delete_watchlist_item(
        session,
        subscription_id=subscription_id,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")

    return _serialize_subscription(subscription)


def _verify_site_matches_request(request: Request, site_id: str) -> None:
    if request.headers.get("X-Savello-Site", "").strip() != site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")


def _serialize_subscription(
    subscription: UserProductSubscription,
) -> WatchlistItemResponse:
    tracked_product = subscription.tracked_product
    return WatchlistItemResponse(
        subscription_id=subscription.id,
        tracked_product_id=subscription.tracked_product_id,
        site_id=subscription.site_id,
        external_user_id=subscription.external_user_id,
        product_url=tracked_product.canonical_url,
        source=tracked_product.source,
        external_product_id=tracked_product.external_product_id,
        region_code=tracked_product.region_code,
        target_price=_format_money(subscription.target_price),
        target_effective_price=_format_money(subscription.target_effective_price),
        is_active=subscription.is_active,
    )


def _format_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"
