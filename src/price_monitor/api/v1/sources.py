from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session, verify_wordpress_request
from price_monitor.core.security import VerifiedRequest
from price_monitor.domains.sources.models import SourceStatus
from price_monitor.domains.sources.schemas import MonitoredSourceResponse
from price_monitor.domains.sources.service import SourceService

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("/status")
def source_status(
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, list[dict[str, str | None]]]:
    statuses = session.scalars(select(SourceStatus).order_by(SourceStatus.source_domain)).all()
    return {
        "sources": [
            {
                "source_domain": status.source_domain,
                "status": status.status,
                "reason": status.reason,
                "checked_at": status.checked_at.isoformat(),
            }
            for status in statuses
        ]
    }


@router.get("/supported")
def supported_source(
    request: Request,
    url: str,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    del verified
    if len(request.query_params.getlist("url")) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="duplicate url query params are not allowed",
        )
    source = SourceService(session).find_supported_source(url)
    if source is None:
        return {
            "supported": False,
            "error": {"code": "unsupported_store", "message": "Магазин не поддерживается"},
        }

    return {
        "supported": True,
        "source": MonitoredSourceResponse(
            source_domain=source.source_domain,
            display_name=source.display_name,
            logo_url=source.logo_url,
            status=source.status,
            fetch_interval_hours=source.fetch_interval_hours,
            history_retention_days=source.history_retention_days,
            browser_fallback_allowed=source.browser_fallback_allowed,
            proxy_pool_id=source.proxy_pool_id,
        ).model_dump(),
    }
