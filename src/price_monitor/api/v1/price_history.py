from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session
from price_monitor.domains.pricing.models import PricePoint

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/{product_id}/price-history")
def price_history(
    product_id: str, session: Annotated[Session, Depends(get_db_session)]
) -> dict[str, object]:
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
