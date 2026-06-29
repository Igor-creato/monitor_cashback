from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session
from price_monitor.domains.sources.models import SourceStatus

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
