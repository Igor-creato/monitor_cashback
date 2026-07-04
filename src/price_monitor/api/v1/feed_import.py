from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from price_monitor.price_compare.auth import require_signed_request
from price_monitor.workers.tasks.feed_import import run_feed_import

router = APIRouter(prefix="/api/v1/feed-import", tags=["price-comparison-feed-import"])


@router.post("/runs", dependencies=[Depends(require_signed_request)])
def create_feed_import_run() -> JSONResponse:
    task = run_feed_import.delay()
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "accepted",
            "task_id": task.id,
            "poll_url": "/api/v1/stores",
        },
    )
