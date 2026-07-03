from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from price_monitor.db.session import get_session
from price_monitor.price_compare.auth import require_signed_request
from price_monitor.price_compare.live.models import LiveSearchRun
from price_monitor.price_compare.live.repository import LiveSearchRunRepository
from price_monitor.price_compare.live.schemas import LiveSearchRequest, LiveSearchRunResponse
from price_monitor.workers.tasks.live_search import run_live_search

router = APIRouter(prefix="/api/v1/live-search", tags=["price-comparison-live"])


@router.post("/runs", dependencies=[Depends(require_signed_request)])
def create_live_search_run(
    request: LiveSearchRequest, session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    query = request.query.strip()
    city = request.city.strip()
    if not city:
        return _safe_error(status.HTTP_400_BAD_REQUEST, "INVALID_CITY", "Укажите город для поиска")
    if not query:
        return _safe_error(status.HTTP_400_BAD_REQUEST, "INVALID_QUERY", "Укажите название товара")

    try:
        run = LiveSearchRunRepository(session).create_run(
            query=query,
            city=city,
            stores=request.stores,
            limit=request.limit,
            timeout_seconds=request.timeout_seconds,
        )
    except SQLAlchemyError:
        return _safe_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "LIVE_SEARCH_BACKEND_UNAVAILABLE",
            "Live поиск временно недоступен",
        )

    run_live_search.delay(run.run_id)
    payload = LiveSearchRunResponse(
        status="accepted",
        run_id=run.run_id,
        poll_url=f"/api/v1/live-search/runs/{run.run_id}",
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload.model_dump())


@router.get("/runs/{run_id}", dependencies=[Depends(require_signed_request)])
def get_live_search_run(
    run_id: str, session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    run = LiveSearchRunRepository(session).get_run(run_id)
    if run is None:
        return _safe_error(
            status.HTTP_404_NOT_FOUND,
            "LIVE_SEARCH_NOT_FOUND",
            "Live поиск не найден",
        )

    payload = _run_payload(run)
    return JSONResponse(content=payload)


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


def _run_payload(run: LiveSearchRun) -> dict[str, object]:
    if run.status in {"queued", "running"}:
        store_statuses = run.progress_payload.get("store_statuses", [])
        if not isinstance(store_statuses, list):
            store_statuses = []
        return {
            "status": "running",
            "progress": run.progress_payload,
            "items": [],
            "store_statuses": store_statuses,
        }

    result = run.result_payload
    store_statuses = result.get("store_statuses", [])
    if not isinstance(store_statuses, list):
        store_statuses = []
    items = result.get("items", [])
    if not isinstance(items, list):
        items = []
    meta = result.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    return {
        "status": run.status,
        "progress": run.progress_payload,
        "items": items,
        "store_statuses": store_statuses,
        "meta": meta,
    }
