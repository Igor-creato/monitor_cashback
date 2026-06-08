from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.clients.cashback_api import CashbackAPIError
from app.db import SessionLocal
from app.fetchers.base import FetchError, PriceFetchResult
from app.models.monitoring import FetchJob, PriceHistory
from app.services.product_cashback import resolve_and_store_product_cashback

logger = logging.getLogger(__name__)


def run_http_fetch_job(job_id, fetcher):
    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as session:
        job = session.get(FetchJob, job_id)
        if job is None or job.status != "queued":
            return None

        job.status = "running"
        job.started_at = _now()
        session.commit()

        tracked_product = job.tracked_product

        try:
            result = fetcher.fetch(tracked_product.canonical_url)
        except Exception as exc:
            error_type = _error_type(exc)
            job.status = "failed"
            job.finished_at = _now()
            job.error_text = _error_text(error_type, exc)
            tracked_product.fail_count = (tracked_product.fail_count or 0) + 1
            tracked_product.last_status = error_type
            session.commit()
            return None

        _apply_success(job, result)
        session.add(_price_history(job.tracked_product_id, result))
        try:
            resolve_and_store_product_cashback(
                job.tracked_product_id,
                price=result.price_current,
                currency=result.currency,
                region_code=tracked_product.region_code,
                session=session,
            )
        except CashbackAPIError:
            logger.warning(
                "cashback_resolution_after_fetch_failed",
                extra={
                    "job_id": job.id,
                    "tracked_product_id": job.tracked_product_id,
                },
                exc_info=True,
            )
        session.commit()
        return None


def _apply_success(job: FetchJob, result: PriceFetchResult) -> None:
    tracked_product = job.tracked_product
    fetched_at = _db_datetime(result.fetched_at)

    tracked_product.product_name = result.product_name
    tracked_product.last_price = result.price_current
    tracked_product.last_old_price = result.price_old
    tracked_product.currency = result.currency
    tracked_product.last_availability = result.availability
    tracked_product.image_url = result.image_url
    tracked_product.last_checked_at = fetched_at
    tracked_product.last_success_at = fetched_at
    tracked_product.last_status = "ok"
    tracked_product.fail_count = 0

    job.status = "done"
    job.finished_at = _now()
    job.error_text = None


def _price_history(tracked_product_id: int, result: PriceFetchResult) -> PriceHistory:
    return PriceHistory(
        tracked_product_id=tracked_product_id,
        price_current=result.price_current,
        price_old=result.price_old,
        currency=result.currency,
        availability=result.availability,
        seller_name=result.seller_name,
        fetched_at=_db_datetime(result.fetched_at),
    )


def _error_type(exc: Exception) -> str:
    if isinstance(exc, FetchError):
        return exc.error_type
    return type(exc).__name__


def _error_text(error_type: str, exc: Exception) -> str:
    message = str(exc)
    text = error_type if not message else f"{error_type}: {message}"
    return text[:500]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
