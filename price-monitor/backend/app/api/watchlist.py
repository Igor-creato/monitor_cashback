from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.models.monitoring import TrackedProduct, UserProductSubscription
from app.schemas.watchlist import (
    WatchlistCashbackLinkRequest,
    WatchlistCashbackLinkResponse,
    WatchlistItemCashbackResponse,
    WatchlistItemCreate,
    WatchlistItemCreateResponse,
    WatchlistItemPatch,
    WatchlistItemResponse,
    WatchlistItemsResponse,
    WatchlistItemWithCashbackResponse,
)
from app.schemas.watchlist_ui import WatchlistUiResponse
from app.services.deeplink import (
    DeeplinkCreationError,
    DeeplinkUnavailable,
    create_cashback_deeplink,
)
from app.services.fetch_job_dispatcher import dispatch_fetch_job
from app.services.fetch_jobs import enqueue_fetch_job
from app.services.product_cards import build_product_card
from app.services.user_limits import get_price_monitor_limits
from app.services.watchlist import (
    UnsupportedWatchlistSourceError,
    WatchlistAddResult,
    WatchlistLimitExceededError,
    add_watchlist_item,
    delete_watchlist_item,
    list_watchlist_items,
    patch_watchlist_item,
)
from app.services.watchlist_ui import build_watchlist_ui_response

router = APIRouter(
    prefix="/v1/watchlist",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/items", response_model=WatchlistItemCreateResponse)
def create_watchlist_item(
    item: WatchlistItemCreate,
    request: Request,
    session: DbSession,
) -> WatchlistItemCreateResponse:
    _verify_site_matches_request(request, item.site_id)
    try:
        result = add_watchlist_item(
            session,
            item,
            limits_provider=get_price_monitor_limits,
        )
    except UnsupportedWatchlistSourceError as exc:
        raise HTTPException(
            status_code=400,
            detail="unsupported_monitoring_store",
        ) from exc
    except WatchlistLimitExceededError as exc:
        raise HTTPException(
            status_code=422,
            detail="max_tracked_products_exceeded",
        ) from exc

    enqueue_fetch_job(
        session,
        result.subscription.tracked_product_id,
        "manual_watchlist_add",
        priority=2,
        job_dispatcher=dispatch_fetch_job,
    )

    return _serialize_create_result(result)


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
        items=[
            _serialize_subscription_with_cashback(subscription)
            for subscription in subscriptions
        ],
        limit=limit,
    )


@router.get(
    "/ui",
    response_model=WatchlistUiResponse,
    response_model_exclude_none=True,
)
def get_watchlist_ui(
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
    include_chart_summary: bool = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WatchlistUiResponse:
    _verify_site_matches_request(request, site_id)
    return build_watchlist_ui_response(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
        include_chart_summary=include_chart_summary,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/items/{subscription_id}/cashback-link",
    response_model=WatchlistCashbackLinkResponse,
)
def create_watchlist_cashback_link(
    subscription_id: int,
    link_request: WatchlistCashbackLinkRequest,
    request: Request,
    session: DbSession,
) -> WatchlistCashbackLinkResponse:
    _verify_site_matches_request(request, link_request.site_id)
    subscription = session.scalar(
        select(UserProductSubscription)
        .options(
            joinedload(UserProductSubscription.tracked_product).joinedload(
                TrackedProduct.cashback
            )
        )
        .where(
            UserProductSubscription.id == subscription_id,
            UserProductSubscription.site_id == link_request.site_id,
            UserProductSubscription.external_user_id == link_request.external_user_id,
            UserProductSubscription.is_active.is_(True),
        )
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")

    try:
        cashback_url = create_cashback_deeplink(
            subscription.tracked_product_id,
            subscription.id,
            session=session,
        )
    except DeeplinkCreationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cashback API is unavailable.",
        ) from exc

    if isinstance(cashback_url, DeeplinkUnavailable):
        raise HTTPException(
            status_code=422,
            detail="Cashback is unavailable for this product",
        )

    snapshot = subscription.tracked_product.cashback
    return WatchlistCashbackLinkResponse(
        cashback_url=cashback_url,
        link_type="deeplink",
        cashback_status=snapshot.cashback_status if snapshot else "unknown",
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
        region_code=subscription.region_code or tracked_product.region_code,
        target_price=_format_money(subscription.target_price),
        target_effective_price=_format_money(subscription.target_effective_price),
        is_active=subscription.is_active,
    )


def _serialize_create_result(
    result: WatchlistAddResult,
) -> WatchlistItemCreateResponse:
    base_item = _serialize_subscription(result.subscription)
    return WatchlistItemCreateResponse(
        **base_item.model_dump(),
        result=result.status,
    )


def _serialize_subscription_with_cashback(
    subscription: UserProductSubscription,
) -> WatchlistItemWithCashbackResponse:
    base_item = _serialize_subscription(subscription)
    card = build_product_card(subscription.tracked_product, subscription)
    item = base_item.model_dump()
    item.update(card.model_dump())
    return WatchlistItemWithCashbackResponse(
        **item,
    )


def _serialize_cashback(
    subscription: UserProductSubscription,
) -> WatchlistItemCashbackResponse:
    snapshot = subscription.tracked_product.cashback
    if snapshot is None:
        return WatchlistItemCashbackResponse(
            cashback_status="unknown",
            cashback_available=False,
            display_policy="cashback_unknown_requires_check",
        )

    return WatchlistItemCashbackResponse(
        cashback_status=snapshot.cashback_status,
        cashback_available=snapshot.cashback_status
        not in {"no_partner", "partner_unknown_product"},
        merchant_id=snapshot.merchant_id,
        merchant_name=snapshot.merchant_name,
        network=snapshot.network,
        offer_id=snapshot.offer_id,
        user_cashback_exact_rate=_format_rate(snapshot.user_cashback_exact_rate),
        user_cashback_min_rate=_format_rate(snapshot.user_cashback_min_rate),
        user_cashback_max_rate=_format_rate(snapshot.user_cashback_max_rate),
        expected_cashback_exact=_format_money(snapshot.expected_cashback_exact),
        expected_cashback_min=_format_money(snapshot.expected_cashback_min),
        expected_cashback_max=_format_money(snapshot.expected_cashback_max),
        effective_price=_format_money(snapshot.effective_price),
        effective_price_conservative=_format_money(
            snapshot.effective_price_conservative
        ),
        confidence=snapshot.confidence,
        display_policy=snapshot.display_policy,
        message=snapshot.message,
    )


def _format_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _format_rate(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")
