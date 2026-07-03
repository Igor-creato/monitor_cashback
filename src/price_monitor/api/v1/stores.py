from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from price_monitor.db.session import get_session
from price_monitor.price_compare.auth import require_signed_request
from price_monitor.price_compare.models import ImportStatus, Offer, StoreSource
from price_monitor.price_compare.schemas import (
    ImportStatusResponse,
    StoreCreateRequest,
    StoreResponse,
    StoreUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["price-comparison-stores"])


@router.get("/stores", dependencies=[Depends(require_signed_request)])
def list_stores(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    stores = list(
        session.scalars(select(StoreSource).order_by(StoreSource.priority, StoreSource.domain))
    )
    return {"status": "ok", "items": [_serialize_store(session, store) for store in stores]}


@router.post("/stores", dependencies=[Depends(require_signed_request)])
def create_store(
    payload: dict[str, Any], session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    request = _validate_store_create(payload)
    if isinstance(request, JSONResponse):
        return request

    store = StoreSource(
        domain=request.domain,
        display_name=request.display_name,
        active=request.active,
        source_type=request.source_type,
        source_config=request.source_config,
        aliases=[alias for alias in request.aliases if alias != request.domain],
        logo_url=request.logo_url,
        priority=request.priority,
        supports_region=request.supports_region,
        fallback_behavior=request.fallback_behavior,
    )
    session.add(store)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return _safe_error(status.HTTP_409_CONFLICT, "STORE_ALREADY_EXISTS", "Магазин уже добавлен")
    except SQLAlchemyError:
        session.rollback()
        return _safe_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STORE_BACKEND_UNAVAILABLE",
            "Настройки магазина временно недоступны",
        )
    session.refresh(store)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=_serialize_store(session, store),
    )


@router.patch("/stores/{store_id}", dependencies=[Depends(require_signed_request)])
def update_store(
    store_id: int, payload: dict[str, Any], session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    store = session.get(StoreSource, store_id)
    if store is None:
        return _safe_error(status.HTTP_404_NOT_FOUND, "STORE_NOT_FOUND", "Магазин не найден")

    request = _validate_store_update(payload)
    if isinstance(request, JSONResponse):
        return request

    changes = request.model_dump(exclude_unset=True)
    aliases = changes.pop("aliases", None)
    for field, value in changes.items():
        setattr(store, field, value)
    if aliases is not None:
        store.aliases = [alias for alias in aliases if alias != store.domain]
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        return _safe_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STORE_BACKEND_UNAVAILABLE",
            "Настройки магазина временно недоступны",
        )
    session.refresh(store)
    return JSONResponse(content=_serialize_store(session, store))


@router.delete("/stores/{store_id}", dependencies=[Depends(require_signed_request)])
def deactivate_store(
    store_id: int, session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    store = session.get(StoreSource, store_id)
    if store is None:
        return _safe_error(status.HTTP_404_NOT_FOUND, "STORE_NOT_FOUND", "Магазин не найден")
    store.active = False
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        return _safe_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STORE_BACKEND_UNAVAILABLE",
            "Настройки магазина временно недоступны",
        )
    session.refresh(store)
    return JSONResponse(content=_serialize_store(session, store))


def _validate_store_create(payload: dict[str, Any]) -> StoreCreateRequest | JSONResponse:
    try:
        return StoreCreateRequest.model_validate(payload)
    except ValidationError as exc:
        return _validation_error(exc)


def _validate_store_update(payload: dict[str, Any]) -> StoreUpdateRequest | JSONResponse:
    try:
        return StoreUpdateRequest.model_validate(payload)
    except ValidationError as exc:
        return _validation_error(exc)


def _validation_error(exc: ValidationError) -> JSONResponse:
    error_code = "INVALID_STORE"
    message = "Проверьте настройки магазина"
    for error in exc.errors():
        if "invalid_logo_url" in str(error):
            error_code = "INVALID_LOGO_URL"
            message = "Логотип магазина должен быть публичным HTTP/HTTPS URL"
            break
        if "invalid_domain" in str(error):
            error_code = "INVALID_DOMAIN"
            message = "Укажите корректный домен магазина"
            break
    return _safe_error(status.HTTP_400_BAD_REQUEST, error_code, message)


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


def _serialize_store(session: Session, store: StoreSource) -> dict[str, object]:
    offer_count = (
        session.scalar(
            select(func.count()).select_from(Offer).where(Offer.store_domain == store.domain)
        )
        or 0
    )
    import_status = session.scalars(
        select(ImportStatus)
        .where(ImportStatus.store_domain == store.domain)
        .order_by(ImportStatus.id.desc())
    ).first()
    status_response = (
        ImportStatusResponse(
            source=import_status.source,
            status=import_status.status,
            last_started_at=import_status.last_started_at,
            last_success_at=import_status.last_success_at,
            last_error_at=import_status.last_error_at,
            last_error=import_status.last_error,
            imported_count=import_status.imported_count,
            skipped_count=import_status.skipped_count,
        )
        if import_status is not None
        else None
    )
    return StoreResponse(
        id=store.id,
        domain=store.domain,
        display_name=store.display_name,
        active=store.active,
        source_type=store.source_type,
        source_config=store.source_config,
        aliases=store.aliases,
        logo_url=store.logo_url,
        priority=store.priority,
        supports_region=store.supports_region,
        fallback_behavior=store.fallback_behavior,
        offer_count=offer_count,
        import_status=status_response,
        created_at=store.created_at,
        updated_at=store.updated_at,
    ).model_dump(mode="json")
