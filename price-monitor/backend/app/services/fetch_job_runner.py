from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.clients.cashback_api import CashbackAPIError
from app.db import SessionLocal
from app.fetchers.base import PriceFetchResult
from app.models.monitoring import FetchJob, PriceHistory
from app.services.image_storage import StoredImage, store_product_image
from app.services.multistage_fetch_executor import (
    FetchPipelineFailed,
    ProductFetchExecutionContext,
    execute_product_fetch,
)
from app.services.notifications import evaluate_price_alerts
from app.services.product_cashback import resolve_and_store_product_cashback

logger = logging.getLogger(__name__)


def run_http_fetch_job(
    job_id,
    fetcher,
    *,
    schema_resolver=None,
    image_store=store_product_image,
    image_transport=None,
    s3_client=None,
    strategy: str = "http_fetch",
    product_fetch_executor=execute_product_fetch,
):
    del strategy

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
            context = ProductFetchExecutionContext(
                session=session,
                fetch_job_id=job.id,
                worker_name=job.worker_name,
                http_fetcher=fetcher,
                schema_resolver=schema_resolver,
            )
            result = product_fetch_executor(job.tracked_product_id, context)
            image_url, image_object_key = _copy_image(
                tracked_product.id,
                result.image_url,
                image_store=image_store,
                image_transport=image_transport,
                s3_client=s3_client,
            )
        except FetchPipelineFailed as exc:
            _apply_failure(job, exc.last_error_type, exc)
            session.commit()
            return None

        _apply_success(
            job,
            result,
            image_url=image_url,
            image_object_key=image_object_key,
        )
        session.add(_price_history(job.tracked_product_id, result))
        session.commit()
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
        evaluate_price_alerts(job.tracked_product_id)
        return None


def _apply_success(
    job: FetchJob,
    result: PriceFetchResult,
    *,
    image_url: str | None,
    image_object_key: str | None,
) -> None:
    tracked_product = job.tracked_product
    fetched_at = _db_datetime(result.fetched_at)

    tracked_product.product_name = result.product_name
    tracked_product.last_price = result.price_current
    tracked_product.last_old_price = result.price_old
    tracked_product.currency = result.currency
    tracked_product.last_availability = result.availability
    tracked_product.image_url = image_url
    tracked_product.image_object_key = image_object_key
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


def _apply_failure(job: FetchJob, error_type: str, exc: Exception) -> None:
    tracked_product = job.tracked_product
    job.status = "failed"
    job.finished_at = _now()
    job.error_text = _error_text(error_type, exc)
    tracked_product.fail_count = (tracked_product.fail_count or 0) + 1
    tracked_product.last_status = error_type


def _copy_image(
    tracked_product_id: int,
    image_url: str | None,
    *,
    image_store,
    image_transport,
    s3_client,
) -> tuple[str | None, str | None]:
    if not image_url:
        return None, None

    try:
        stored = image_store(
            tracked_product_id,
            image_url,
            transport=image_transport,
            s3_client=s3_client,
        )
    except Exception:
        logger.warning(
            "product_image_copy_after_fetch_failed",
            extra={"tracked_product_id": tracked_product_id},
            exc_info=True,
        )
        return image_url, None

    if isinstance(stored, StoredImage) and stored.copied:
        return stored.image_url, stored.object_key
    if isinstance(stored, StoredImage):
        return stored.image_url, None
    return image_url, None


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
