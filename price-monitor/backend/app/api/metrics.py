from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.metrics import render_prometheus_metrics

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics")
def metrics(session: DbSession) -> Response:
    return Response(
        content=render_prometheus_metrics(session),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )
