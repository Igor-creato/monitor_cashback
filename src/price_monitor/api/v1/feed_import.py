from __future__ import annotations

import re
from collections.abc import Mapping

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from price_monitor.price_compare.auth import require_signed_request
from price_monitor.workers.tasks.feed_import import run_feed_import

router = APIRouter(prefix="/api/v1/feed-import", tags=["price-comparison-feed-import"])

_TASK_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,160}\Z")
_SAFE_RESULT_KEYS = (
    "status",
    "created_count",
    "updated_count",
    "skipped_count",
    "quarantined_count",
)


@router.post("/runs", dependencies=[Depends(require_signed_request)])
def create_feed_import_run() -> JSONResponse:
    task = run_feed_import.delay()
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "accepted",
            "task_id": task.id,
            "poll_url": f"/api/v1/feed-import/tasks/{task.id}",
        },
    )


@router.get("/tasks/{task_id}", dependencies=[Depends(require_signed_request)])
def get_feed_import_task(task_id: str) -> JSONResponse:
    if _TASK_ID_RE.fullmatch(task_id) is None:
        return _safe_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_FEED_IMPORT_TASK",
            "Некорректный идентификатор импорта.",
        )

    task = run_feed_import.AsyncResult(task_id)
    state = str(getattr(task, "state", "PENDING")).lower()
    content: dict[str, object] = {
        "status": "ok",
        "task_id": task_id,
        "state": state,
    }
    info = getattr(task, "info", None)
    if isinstance(info, Mapping):
        safe_result = {key: info[key] for key in _SAFE_RESULT_KEYS if key in info}
        if safe_result:
            content["result"] = safe_result
    elif state == "failure":
        content["result"] = {
            "status": "failed",
            "error_code": "feed_import_failed",
        }

    return JSONResponse(content=content)


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
