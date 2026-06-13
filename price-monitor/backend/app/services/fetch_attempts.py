from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import FetchAttempt

SUCCESS_STATUS = "success"


def record_fetch_attempt(
    *,
    tracked_product_id: int,
    source_code: str,
    strategy: str,
    status: str,
    fetch_job_id: int | None = None,
    proxy_pool_id: int | None = None,
    proxy_endpoint_id: int | None = None,
    worker_name: str | None = None,
    error_type: str | None = None,
    http_status: int | None = None,
    response_ms: int | None = None,
    cost_estimated: Decimal | None = None,
    bytes_downloaded: int | None = None,
    product_data_found: bool = False,
    price_found: bool = False,
    image_found: bool = False,
    session: Session | None = None,
) -> FetchAttempt:
    attempt = FetchAttempt(
        tracked_product_id=tracked_product_id,
        source_code=source_code,
        strategy=strategy,
        status=status,
        fetch_job_id=fetch_job_id,
        proxy_pool_id=proxy_pool_id,
        proxy_endpoint_id=proxy_endpoint_id,
        worker_name=worker_name,
        error_type=error_type,
        http_status=http_status,
        response_ms=response_ms,
        cost_estimated=cost_estimated,
        bytes_downloaded=bytes_downloaded,
        product_data_found=product_data_found,
        price_found=price_found,
        image_found=image_found,
    )

    if session is not None:
        return _persist(session, attempt)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _persist(owned_session, attempt)


def get_cost_per_success(
    source_code: str,
    period: timedelta,
    *,
    now: datetime | None = None,
    session: Session | None = None,
) -> Decimal:
    cutoff = _as_utc_naive((now or datetime.now(UTC)) - period)

    if session is not None:
        return _cost_per_success(session, source_code, cutoff)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _cost_per_success(owned_session, source_code, cutoff)


def get_strategy_success_rate(
    source_code: str,
    strategy: str,
    period: timedelta,
    *,
    now: datetime | None = None,
    session: Session | None = None,
) -> float:
    cutoff = _as_utc_naive((now or datetime.now(UTC)) - period)

    if session is not None:
        return _strategy_success_rate(session, source_code, strategy, cutoff)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _strategy_success_rate(owned_session, source_code, strategy, cutoff)


def _persist(session: Session, attempt: FetchAttempt) -> FetchAttempt:
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return attempt


def _cost_per_success(
    session: Session,
    source_code: str,
    cutoff: datetime,
) -> Decimal:
    total_cost = session.scalar(
        select(func.coalesce(func.sum(FetchAttempt.cost_estimated), 0)).where(
            FetchAttempt.source_code == source_code,
            FetchAttempt.created_at >= cutoff,
        )
    )
    success_count = (
        session.scalar(
            select(func.count(FetchAttempt.id)).where(
                FetchAttempt.source_code == source_code,
                FetchAttempt.status == SUCCESS_STATUS,
                FetchAttempt.created_at >= cutoff,
            )
        )
        or 0
    )

    if success_count == 0:
        return Decimal("0")

    return Decimal(str(total_cost)) / Decimal(success_count)


def _strategy_success_rate(
    session: Session,
    source_code: str,
    strategy: str,
    cutoff: datetime,
) -> float:
    total = (
        session.scalar(
            select(func.count(FetchAttempt.id)).where(
                FetchAttempt.source_code == source_code,
                FetchAttempt.strategy == strategy,
                FetchAttempt.created_at >= cutoff,
            )
        )
        or 0
    )

    if total == 0:
        return 0.0

    success = (
        session.scalar(
            select(func.count(FetchAttempt.id)).where(
                FetchAttempt.source_code == source_code,
                FetchAttempt.strategy == strategy,
                FetchAttempt.status == SUCCESS_STATUS,
                FetchAttempt.created_at >= cutoff,
            )
        )
        or 0
    )

    return success / total


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
