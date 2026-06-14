from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.clients.cashback_api import CashbackAPIError
from app.db import SessionLocal
from app.extraction import (
    ExtractedProductData,
    ExtractionError,
    ExtractionSchema,
    PriceNotFoundError,
    RequiredFieldNotFoundError,
    extract_product_data,
)
from app.fetchers.base import FetchError, PriceFetchResult
from app.models.monitoring import FetchJob, PriceHistory
from app.services.fetch_attempts import record_fetch_attempt
from app.services.image_storage import StoredImage, store_product_image
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
):
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

        page_metadata: dict[str, int | None] = {}
        product_data_found = False
        price_found = False
        image_found = False
        try:
            schema = _resolve_schema(schema_resolver, tracked_product)
            if schema is None:
                result = fetcher.fetch(tracked_product.canonical_url)
            else:
                page = fetcher.fetch_page(tracked_product.canonical_url)
                page_metadata = {
                    "http_status": page.http_status,
                    "response_ms": page.response_ms,
                    "bytes_downloaded": page.bytes_downloaded,
                }
                extracted = extract_product_data(page.content, schema)
                result = _result_from_extracted(
                    extracted,
                    page.fetched_at,
                    default_currency=tracked_product.currency,
                )

            product_data_found = True
            price_found = result.price_current is not None
            image_found = bool(result.image_url)
            image_url, image_object_key = _copy_image(
                tracked_product.id,
                result.image_url,
                image_store=image_store,
                image_transport=image_transport,
                s3_client=s3_client,
            )
        except Exception as exc:
            error_type = _error_type(exc)
            job.status = "failed"
            job.finished_at = _now()
            job.error_text = _error_text(error_type, exc)
            tracked_product.fail_count = (tracked_product.fail_count or 0) + 1
            tracked_product.last_status = error_type
            _record_attempt(
                session,
                job,
                strategy=strategy,
                status="failed",
                error_type=error_type,
                product_data_found=product_data_found,
                price_found=price_found,
                image_found=image_found,
                **page_metadata,
            )
            return None

        _apply_success(
            job,
            result,
            image_url=image_url,
            image_object_key=image_object_key,
        )
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
        evaluate_price_alerts(job.tracked_product_id)
        _record_attempt(
            session,
            job,
            strategy=strategy,
            status="success",
            error_type=None,
            product_data_found=product_data_found,
            price_found=price_found,
            image_found=image_found,
            **page_metadata,
        )
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


def _resolve_schema(schema_resolver, tracked_product) -> ExtractionSchema | None:
    if schema_resolver is None:
        return None
    return schema_resolver(tracked_product)


def _result_from_extracted(
    extracted: ExtractedProductData,
    fetched_at: datetime,
    *,
    default_currency: str | None,
) -> PriceFetchResult:
    if extracted.price_current is None:
        raise PriceNotFoundError()

    availability = (
        extracted.availability if extracted.availability is not None else True
    )
    return PriceFetchResult(
        product_name=extracted.title,
        price_current=extracted.price_current,
        price_old=extracted.price_old,
        currency=extracted.currency or default_currency or "RUB",
        availability=availability,
        seller_name=extracted.seller_name,
        image_url=extracted.image_url,
        fetched_at=fetched_at,
    )


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


def _record_attempt(
    session,
    job: FetchJob,
    *,
    strategy: str,
    status: str,
    error_type: str | None,
    product_data_found: bool,
    price_found: bool,
    image_found: bool,
    http_status: int | None = None,
    response_ms: int | None = None,
    bytes_downloaded: int | None = None,
) -> None:
    record_fetch_attempt(
        tracked_product_id=job.tracked_product_id,
        source_code=job.tracked_product.source,
        strategy=strategy,
        status=status,
        fetch_job_id=job.id,
        worker_name=job.worker_name,
        error_type=error_type,
        http_status=http_status,
        response_ms=response_ms,
        bytes_downloaded=bytes_downloaded,
        product_data_found=product_data_found,
        price_found=price_found,
        image_found=image_found,
        session=session,
    )


def _error_type(exc: Exception) -> str:
    if isinstance(exc, FetchError):
        return exc.error_type
    if isinstance(exc, PriceNotFoundError):
        return "price_not_found"
    if isinstance(exc, RequiredFieldNotFoundError | ExtractionError):
        return "parser_error"
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
