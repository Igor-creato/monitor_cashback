from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session, verify_wordpress_request
from price_monitor.core.idempotency import (
    IdempotencyReplay,
    complete_idempotency_record,
    get_replay_or_reserve,
)
from price_monitor.core.security import VerifiedRequest
from price_monitor.domains.sources.schemas import (
    MonitoredSourceListResponse,
    MonitoredSourceRequest,
    MonitoredSourceResponse,
    MonitorSettingsPatchRequest,
    MonitorSettingsResponse,
)
from price_monitor.domains.sources.service import (
    InvalidMonitoredSourceError,
    MonitoredSourceInput,
    SourceService,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/sources", response_model=None)
def create_source(
    payload: MonitoredSourceRequest,
    response: Response,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not idempotency_key:
        return _idempotency_required()

    route = "POST /api/v1/admin/sources"
    reserved = get_replay_or_reserve(
        session=session,
        key=idempotency_key,
        route=route,
        request_hash=verified.body_sha256,
    )
    if isinstance(reserved, IdempotencyReplay):
        return JSONResponse(status_code=reserved.status_code, content=reserved.response_body)

    try:
        source = SourceService(session).upsert_source(MonitoredSourceInput(**payload.model_dump()))
    except InvalidMonitoredSourceError as exc:
        return _validation_error(str(exc))
    response.status_code = status.HTTP_201_CREATED
    response_body = {"source": _serialize_source(source).model_dump()}
    complete_idempotency_record(
        record=reserved,
        status_code=response.status_code,
        response_body=_json_ready(response_body),
    )
    session.commit()
    return response_body


@router.get("/sources", response_model=MonitoredSourceListResponse)
def list_sources(
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MonitoredSourceListResponse:
    del verified
    sources = SourceService(session).list_sources()
    return MonitoredSourceListResponse(sources=[_serialize_source(source) for source in sources])


@router.patch("/settings", response_model=None)
def update_settings(
    payload: MonitorSettingsPatchRequest,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if not idempotency_key:
        return _idempotency_required()

    route = "PATCH /api/v1/admin/settings"
    reserved = get_replay_or_reserve(
        session=session,
        key=idempotency_key,
        route=route,
        request_hash=verified.body_sha256,
    )
    if isinstance(reserved, IdempotencyReplay):
        return JSONResponse(status_code=reserved.status_code, content=reserved.response_body)

    settings = SourceService(session).update_settings(_settings_payload_values(payload))
    response_body = MonitorSettingsResponse(settings=_typed_settings(settings)).model_dump()
    complete_idempotency_record(
        record=reserved,
        status_code=status.HTTP_200_OK,
        response_body=_json_ready(response_body),
    )
    session.commit()
    return MonitorSettingsResponse(settings=response_body["settings"])


@router.get("/settings", response_model=MonitorSettingsResponse)
def get_settings(
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MonitorSettingsResponse:
    del verified
    return MonitorSettingsResponse(settings=_typed_settings(SourceService(session).get_settings()))


def _serialize_source(source: Any) -> MonitoredSourceResponse:
    return MonitoredSourceResponse(
        source_domain=source.source_domain,
        display_name=source.display_name,
        logo_url=source.logo_url,
        status=source.status,
        fetch_interval_hours=source.fetch_interval_hours,
        history_retention_days=source.history_retention_days,
        browser_fallback_allowed=source.browser_fallback_allowed,
        proxy_pool_id=source.proxy_pool_id,
    )


def _settings_payload_values(payload: MonitorSettingsPatchRequest) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in payload.model_dump(exclude_none=True).items():
        values[key] = str(value)
    return values


def _typed_settings(settings: dict[str, str]) -> dict[str, int | float | str | bool]:
    provider_url = settings["joom_browser_provider_url"].strip()
    provider_token = settings["joom_browser_provider_token"].strip()
    wait_selector = settings["joom_browser_provider_wait_selector"].strip()
    return {
        "max_tracked_products_per_user": int(settings["max_tracked_products_per_user"]),
        "price_refresh_interval_hours": int(settings["price_refresh_interval_hours"]),
        "joom_browser_provider_url": provider_url,
        "joom_browser_provider_timeout_seconds": float(
            settings["joom_browser_provider_timeout_seconds"]
        ),
        "joom_browser_provider_wait_selector": wait_selector,
        "joom_browser_provider_configured": bool(provider_url),
        "joom_browser_provider_token_set": bool(provider_token),
    }


def _idempotency_required() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {"code": "idempotency_key_required", "message": "Idempotency-Key required"}
        },
    )


def _validation_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": "validation_failed", "message": message}},
    )


def _json_ready(value: dict[str, Any]) -> dict[str, Any]:
    return value
