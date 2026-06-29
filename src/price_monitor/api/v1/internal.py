from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session
from price_monitor.domains.reliability.models import OutboxEvent

router = APIRouter(prefix="/api/v1/internal", tags=["internal"], include_in_schema=False)


@router.get("/outbox/pending-count")
def outbox_pending_count(session: Annotated[Session, Depends(get_db_session)]) -> dict[str, int]:
    pending = session.scalars(select(OutboxEvent).where(OutboxEvent.status == "pending")).all()
    return {"pending": len(pending)}
