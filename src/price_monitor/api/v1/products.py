from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session, verify_wordpress_request
from price_monitor.core.security import VerifiedRequest
from price_monitor.domains.products.models import Product
from price_monitor.domains.sources.models import MonitoredSource

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/{product_id}", response_model=None)
def product_detail(
    product_id: str,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
) -> object:
    del verified
    product = session.get(Product, product_id)
    if product is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "product_not_found", "message": "Товар не найден"}},
        )
    source = session.get(MonitoredSource, product.source_domain)
    if source is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "source_not_found", "message": "Источник не найден"}},
        )

    return {
        "product": {
            "id": product.id,
            "canonical_url": product.canonical_url,
            "title": product.title,
            "image_url": product.image_url,
            "rating_value": product.rating_value,
            "current_price_minor": product.current_price_minor,
            "currency": product.currency,
            "last_fetch_status": product.last_fetch_status,
        },
        "source": {
            "source_domain": source.source_domain,
            "display_name": source.display_name,
            "logo_url": source.logo_url,
        },
        "actions": {"direct_url": product.canonical_url},
    }
