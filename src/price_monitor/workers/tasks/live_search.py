from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.db.session import get_session_factory
from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    LiveSearchItem,
    LiveSearchQuery,
    LiveStoreResult,
)
from price_monitor.price_compare.live.adapters.registry import get_adapter_for_store
from price_monitor.price_compare.live.merge import merge_live_results
from price_monitor.price_compare.live.repository import LiveSearchRunRepository
from price_monitor.price_compare.models import StoreSource
from price_monitor.price_compare.schemas import normalize_domain
from price_monitor.workers.celery_app import celery_app


@celery_app.task(name="price_monitor.live_search.run")  # type: ignore[untyped-decorator]
def run_live_search(run_id: str) -> dict[str, object]:
    factory = get_session_factory()
    with factory() as session:
        repo = LiveSearchRunRepository(session)
        run = repo.mark_running(run_id)
        if run is None:
            return {"status": "not_found", "run_id": run_id}

        store_results: list[LiveStoreResult] = []
        store_statuses: list[dict[str, object]] = []
        stores = _active_stores(session, selected=run.stores)
        total = len(stores)
        query = LiveSearchQuery(
            query=run.query,
            city=run.city,
            limit=_adapter_fetch_limit(run.limit),
        )

        for index, store in enumerate(stores, start=1):
            result = _search_store(store, query)
            store_results.append(result)
            store_statuses.append(_store_status_payload(result))
            repo.store_progress(
                run_id,
                {
                    "total": total,
                    "completed": index,
                    "current_store": store.domain,
                    "store_statuses": store_statuses,
                },
            )

        items = merge_live_results(store_results, query=run.query, limit=run.limit)
        status = _run_status(store_results, items)
        result_payload: dict[str, object] = {
            "items": [_item_payload(item) for item in items],
            "store_statuses": store_statuses,
            "meta": {
                "total": len(items),
                "limit": run.limit,
                "warnings": _warnings(store_results, items),
            },
        }
        repo.store_result(run_id, status=status, result=result_payload)
        return {"status": status, "run_id": run_id, "items": result_payload["items"]}


def _active_stores(session: Session, *, selected: list[str]) -> list[StoreSource]:
    normalized = [normalize_domain(store) for store in selected if store.strip()]
    stmt = select(StoreSource).where(StoreSource.active.is_(True))
    if normalized:
        stmt = stmt.where(StoreSource.domain.in_(normalized))
    return list(session.scalars(stmt).all())


def _search_store(store: StoreSource, query: LiveSearchQuery) -> LiveStoreResult:
    adapter = get_adapter_for_store(
        store.domain,
        {"source_type": store.source_type, "source_config": store.source_config},
    )
    if adapter is None:
        return LiveStoreResult(
            store_domain=store.domain,
            status=STORE_STATUS_FAILED,
            items=[],
            warnings=["live_adapter_not_configured"],
            message="Live поиск для магазина не настроен",
        )
    try:
        return adapter.search(query)
    except Exception:
        return LiveStoreResult(
            store_domain=store.domain,
            status=STORE_STATUS_FAILED,
            items=[],
            warnings=["live_store_failed"],
            message="Магазин временно недоступен",
        )


def _run_status(results: list[LiveStoreResult], items: Sequence[LiveSearchItem]) -> str:
    if not results:
        return "failed"
    blocked_count = sum(1 for result in results if result.status == STORE_STATUS_BLOCKED_BY_ANTIBOT)
    failed_count = sum(1 for result in results if result.status == STORE_STATUS_FAILED)
    if blocked_count == len(results):
        return "blocked"
    if blocked_count or failed_count:
        return "partial" if items else "failed"
    return "ok"


def _store_status_payload(result: LiveStoreResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "store_domain": result.store_domain,
        "status": result.status,
    }
    if result.message:
        payload["message"] = result.message
    if result.warnings:
        payload["warnings"] = result.warnings
    return payload


def _item_payload(item: LiveSearchItem) -> dict[str, object]:
    return {
        "title": item.title,
        "price": _json_price(item.price),
        "currency": item.currency,
        "url": item.url,
        "image_url": item.image_url,
        "availability": item.availability,
        "store_domain": item.store_domain,
        "store_name": item.store_name,
        "category": item.category,
        "brand": item.brand,
        "external_id": item.external_id,
        "relevance_reason": item.relevance_reason,
    }


def _json_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(Decimal(str(value)))


def _warnings(results: list[LiveStoreResult], items: Sequence[LiveSearchItem]) -> list[str]:
    warnings: list[str] = []
    if any(
        result.status in {STORE_STATUS_BLOCKED_BY_ANTIBOT, STORE_STATUS_FAILED}
        for result in results
    ):
        warnings.append("Часть магазинов недоступна")
    if not items:
        warnings.append("Товаров не нашлось")
    return warnings


def _adapter_fetch_limit(limit: int) -> int:
    return min(50, max(limit, limit * 5))
