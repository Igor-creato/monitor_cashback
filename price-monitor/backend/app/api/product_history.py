from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.models.monitoring import PriceHistory
from app.schemas.price_chart import PriceChartGranularity, PriceChartResponse
from app.schemas.product_history import (
    ProductPriceHistoryPoint,
    ProductPriceHistoryResponse,
)
from app.services.price_chart import build_price_chart
from app.services.product_history import list_product_price_history

router = APIRouter(
    prefix="/v1/products",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/{tracked_product_id}/history", response_model=ProductPriceHistoryResponse)
def get_product_price_history(
    tracked_product_id: int,
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=30)] = 30,
) -> ProductPriceHistoryResponse:
    _verify_site_matches_request(request, site_id)
    history = list_product_price_history(
        session,
        tracked_product_id=tracked_product_id,
        site_id=site_id,
        external_user_id=external_user_id,
        days=days,
    )
    if history is None:
        raise HTTPException(status_code=404, detail="Product history not found.")

    return ProductPriceHistoryResponse(
        points=[_serialize_history_point(point) for point in history]
    )


@router.get("/{tracked_product_id}/price-chart", response_model=PriceChartResponse)
def get_product_price_chart(
    tracked_product_id: int,
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    granularity: PriceChartGranularity = "raw",
    currency: str | None = None,
) -> PriceChartResponse:
    _verify_site_matches_request(request, site_id)
    chart = build_price_chart(
        session,
        tracked_product_id=tracked_product_id,
        site_id=site_id,
        external_user_id=external_user_id,
        days=days,
        granularity=granularity,
        currency=currency,
    )
    if chart is None:
        raise HTTPException(status_code=404, detail="Product chart not found.")

    return chart


def _verify_site_matches_request(request: Request, site_id: str) -> None:
    if request.headers.get("X-Savello-Site", "").strip() != site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")


def _serialize_history_point(point: PriceHistory) -> ProductPriceHistoryPoint:
    return ProductPriceHistoryPoint(
        price_current=_format_money(point.price_current),
        price_old=_format_money(point.price_old),
        currency=point.currency,
        availability=point.availability,
        fetched_at=point.fetched_at,
    )


def _format_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"
