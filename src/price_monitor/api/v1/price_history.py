from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session, verify_wordpress_request
from price_monitor.core.security import VerifiedRequest
from price_monitor.domains.fetching.service import summarize_price_chart
from price_monitor.domains.pricing.models import PricePoint
from price_monitor.domains.products.models import Product

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/{product_id}/price-history")
def price_history(
    product_id: str,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    del verified
    points = session.scalars(
        select(PricePoint)
        .where(PricePoint.product_id == product_id)
        .order_by(PricePoint.observed_at.asc())
    ).all()
    return {
        "product_id": product_id,
        "points": [
            {
                "observed_at": point.observed_at.isoformat(),
                "price_minor": point.price_minor,
                "currency": point.currency,
                "source_domain": point.source_domain,
            }
            for point in points
        ],
    }


@router.get("/{product_id}/price-chart")
def price_chart(
    product_id: str,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> object:
    del verified
    product = session.get(Product, product_id)
    if product is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "product_not_found", "message": "Товар не найден"}},
        )

    points = session.scalars(
        select(PricePoint)
        .where(PricePoint.product_id == product_id)
        .order_by(PricePoint.observed_at.asc(), PricePoint.id.asc())
    ).all()
    chart_points, summary, currency = summarize_price_chart(points, days=days)
    return {
        "product_id": product_id,
        "currency": currency or product.currency,
        "points": chart_points,
        "summary": summary,
    }
