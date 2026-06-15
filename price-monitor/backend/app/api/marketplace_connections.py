from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.schemas.marketplace_sessions import (
    MarketplaceConnectionCreate,
    MarketplaceConnectionsResponse,
    MarketplaceConnectionStatusResponse,
)
from app.schemas.price_assistant import (
    MarketplaceSessionBundleAttach,
    OwnerScopedRequest,
    ReconnectRequiredRequest,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyKeyMissingError,
    require_idempotency_key,
    run_idempotent,
)
from app.services.marketplace_sessions import (
    EncryptionConfigurationError,
    MarketplaceDisabledError,
    MarketplaceSessionError,
    attach_session_bundle_to_connection,
    connect_marketplace_session,
    disconnect_marketplace_connection,
    list_marketplace_connections,
    mark_marketplace_connection_reconnect_required,
    serialize_marketplace_connection,
)

router = APIRouter(
    prefix="/v1/marketplace-connections",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=MarketplaceConnectionStatusResponse)
def create_marketplace_connection(
    payload: MarketplaceConnectionCreate,
    request: Request,
    session: DbSession,
) -> MarketplaceConnectionStatusResponse:
    _verify_site_matches_request(request, payload.site_id)
    try:
        connection = connect_marketplace_session(session, payload)
    except MarketplaceDisabledError as exc:
        raise HTTPException(status_code=423, detail=exc.detail) from exc
    except MarketplaceSessionError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except EncryptionConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="session_encryption_unavailable",
        ) from exc
    return serialize_marketplace_connection(connection)


@router.post("/{connection_id}/session-bundle")
async def attach_marketplace_session_bundle(
    connection_id: int,
    payload: MarketplaceSessionBundleAttach,
    request: Request,
    session: DbSession,
):
    _verify_site_matches_request(request, payload.site_id)
    idempotency_key = _idempotency_key_or_http(request)
    raw_body = await request.body()

    def operation():
        attach_request = MarketplaceConnectionCreate(
            site_id=payload.site_id,
            external_user_id=payload.external_user_id,
            marketplace="placeholder",
            consent_version=payload.consent_version,
            scope=payload.scope,
            captured_at=payload.captured_at,
            connector_version=payload.connector_version,
            session_bundle=payload.session_bundle,
            expires_at=payload.expires_at,
        )
        try:
            connection = attach_session_bundle_to_connection(
                session,
                connection_id=connection_id,
                request=attach_request,
            )
        except MarketplaceDisabledError as exc:
            raise HTTPException(status_code=423, detail=exc.detail) from exc
        except MarketplaceSessionError as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        except EncryptionConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail="session_encryption_unavailable",
            ) from exc
        if connection is None:
            raise HTTPException(
                status_code=404,
                detail="Marketplace connection not found.",
            )
        return serialize_marketplace_connection(connection)

    return _run_idempotent_or_http(
        session,
        scope=f"marketplace-session-bundle:{connection_id}",
        idempotency_key=idempotency_key,
        raw_body=raw_body,
        operation=operation,
    )


@router.get("", response_model=MarketplaceConnectionsResponse)
def get_marketplace_connections(
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
) -> MarketplaceConnectionsResponse:
    _verify_site_matches_request(request, site_id)
    return MarketplaceConnectionsResponse(
        items=list_marketplace_connections(
            session,
            site_id=site_id,
            external_user_id=external_user_id,
        )
    )


@router.delete(
    "/{connection_id}",
    response_model=MarketplaceConnectionStatusResponse,
)
def delete_marketplace_connection(
    connection_id: int,
    request: Request,
    site_id: str,
    external_user_id: str,
    session: DbSession,
) -> MarketplaceConnectionStatusResponse:
    _verify_site_matches_request(request, site_id)
    connection = disconnect_marketplace_connection(
        session,
        connection_id=connection_id,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    if connection is None:
        raise HTTPException(
            status_code=404,
            detail="Marketplace connection not found.",
        )
    return serialize_marketplace_connection(connection)


@router.post("/{connection_id}/disconnect")
async def post_disconnect_marketplace_connection(
    connection_id: int,
    payload: OwnerScopedRequest,
    request: Request,
    session: DbSession,
):
    _verify_site_matches_request(request, payload.site_id)
    idempotency_key = _idempotency_key_or_http(request)
    raw_body = await request.body()

    def operation():
        connection = disconnect_marketplace_connection(
            session,
            connection_id=connection_id,
            site_id=payload.site_id,
            external_user_id=payload.external_user_id,
        )
        if connection is None:
            raise HTTPException(
                status_code=404,
                detail="Marketplace connection not found.",
            )
        return serialize_marketplace_connection(connection)

    return _run_idempotent_or_http(
        session,
        scope=f"marketplace-disconnect:{connection_id}",
        idempotency_key=idempotency_key,
        raw_body=raw_body,
        operation=operation,
    )


@router.post("/{connection_id}/reconnect-required")
async def post_marketplace_reconnect_required(
    connection_id: int,
    payload: ReconnectRequiredRequest,
    request: Request,
    session: DbSession,
):
    _verify_site_matches_request(request, payload.site_id)
    idempotency_key = _idempotency_key_or_http(request)
    raw_body = await request.body()

    def operation():
        try:
            connection = mark_marketplace_connection_reconnect_required(
                session,
                connection_id=connection_id,
                site_id=payload.site_id,
                external_user_id=payload.external_user_id,
                reason=payload.reason,
            )
        except MarketplaceSessionError as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        if connection is None:
            raise HTTPException(
                status_code=404,
                detail="Marketplace connection not found.",
            )
        return serialize_marketplace_connection(connection)

    return _run_idempotent_or_http(
        session,
        scope=f"marketplace-reconnect-required:{connection_id}",
        idempotency_key=idempotency_key,
        raw_body=raw_body,
        operation=operation,
    )


def _verify_site_matches_request(request: Request, site_id: str) -> None:
    if request.headers.get("X-Savello-Site", "").strip() != site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")


def _idempotency_key_or_http(request: Request) -> str:
    try:
        return require_idempotency_key(request.headers.get("Idempotency-Key"))
    except IdempotencyKeyMissingError as exc:
        raise HTTPException(status_code=400, detail="idempotency_key_required") from exc


def _run_idempotent_or_http(session, **kwargs):
    try:
        return run_idempotent(session, **kwargs)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail="idempotency_key_conflict") from exc
