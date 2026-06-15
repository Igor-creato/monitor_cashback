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
from app.services.marketplace_sessions import (
    EncryptionConfigurationError,
    MarketplaceDisabledError,
    MarketplaceSessionError,
    connect_marketplace_session,
    disconnect_marketplace_connection,
    list_marketplace_connections,
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


def _verify_site_matches_request(request: Request, site_id: str) -> None:
    if request.headers.get("X-Savello-Site", "").strip() != site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")
