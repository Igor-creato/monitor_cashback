from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from price_monitor.db.session import get_session
from price_monitor.price_compare.auth import require_signed_request
from price_monitor.price_compare.models import Offer
from price_monitor.price_compare.repository import OfferRepository
from price_monitor.price_compare.schemas import SearchRequest

router = APIRouter(prefix="/api/v1", tags=["price-comparison"])


@router.post("/search", dependencies=[Depends(require_signed_request)])
def search(
    request: SearchRequest, session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    query = request.query.strip()
    city = request.city.strip()
    if not city:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "error_code": "INVALID_CITY",
                "message": "Укажите город для поиска",
                "request_id": "",
            },
        )
    if not query:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "error_code": "INVALID_QUERY",
                "message": "Укажите название товара",
                "request_id": "",
            },
        )

    try:
        repository = OfferRepository(session)
        index_state = repository.index_state(stores=request.stores)
        if index_state.active_store_count == 0:
            return _safe_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "SOURCE_UNAVAILABLE",
                "Источники поиска не настроены.",
            )
        if index_state.active_offer_count == 0:
            return _safe_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "SEARCH_INDEX_EMPTY",
                "Индекс поиска пуст. Запустите импорт товаров.",
            )

        results = repository.search(
            query=query,
            city=city,
            stores=request.stores,
            limit=request.limit,
            offset=request.offset,
        )
        store_statuses = repository.store_statuses(stores=request.stores)
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "error_code": "SEARCH_BACKEND_UNAVAILABLE",
                "message": "Ошибка поиска. Источник данных временно недоступен",
                "request_id": "",
            },
        )
    warnings = [] if results.items else ["Товаров не нашлось"]

    return JSONResponse(
        content={
            "status": "ok",
            "query": query,
            "city": city,
            "items": [_serialize_offer(offer) for offer in results.items],
            "meta": {
                "total": results.total,
                "limit": request.limit,
                "offset": request.offset,
                "warnings": warnings,
                "store_statuses": [
                    {
                        "store_domain": store_status.store_domain,
                        "status": store_status.status,
                        "offer_count": store_status.offer_count,
                        "region_supported": store_status.region_supported,
                    }
                    for store_status in store_statuses
                ],
            },
        }
    )


def _safe_error(status_code: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error_code": error_code,
            "message": message,
            "request_id": "",
        },
    )


def _serialize_offer(offer: Offer) -> dict[str, object]:
    public_url = _public_offer_url(offer.url)
    return {
        "id": str(offer.id),
        "source": offer.source,
        "store_domain": offer.store_domain,
        "store_name": offer.store_domain,
        "title": offer.title,
        "price": float(offer.price) if offer.price is not None else None,
        "currency": offer.currency,
        "url": public_url,
        "action_url": public_url,
        "image_url": offer.image_url,
        "availability": offer.availability,
        "region_supported": offer.region_supported,
        "city": offer.city,
        "category": offer.category,
        "brand": offer.brand,
        "external_id": offer.external_id,
        "updated_at": offer.updated_at.isoformat() if offer.updated_at else None,
        "price_updated_at": offer.updated_at.isoformat() if offer.updated_at else None,
        "feed_updated_at": offer.updated_at.isoformat() if offer.updated_at else None,
    }


def _public_offer_url(raw_url: str) -> str:
    if "{link}" not in raw_url:
        return raw_url

    query = raw_url.split("?", 1)[1] if "?" in raw_url else ""
    target_url = parse_qs(query, keep_blank_values=True).get("dl", [""])[0]
    scheme = urlsplit(target_url).scheme.lower()
    if scheme in {"http", "https"}:
        return target_url

    return raw_url.replace("{link}", "").lstrip("?&")
