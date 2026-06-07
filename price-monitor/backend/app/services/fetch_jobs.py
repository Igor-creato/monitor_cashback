from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import FetchJob, TrackedProduct

FETCH_JOB_ACTIVE_STATUSES = ("queued", "running")
FETCH_JOB_FRESHNESS_WINDOW = timedelta(minutes=60)


def enqueue_fetch_job(
    session: Session,
    tracked_product_id,
    reason,
    priority=5,
    *,
    now: datetime | None = None,
) -> str:
    now_utc = _as_utc(now or datetime.now(UTC))
    tracked_product = session.get(TrackedProduct, tracked_product_id)
    if tracked_product is None:
        raise ValueError("Tracked product was not found.")

    existing_job = session.scalar(
        select(FetchJob).where(
            FetchJob.tracked_product_id == tracked_product_id,
            FetchJob.status.in_(FETCH_JOB_ACTIVE_STATUSES),
        )
    )
    if existing_job is not None:
        return "existing"

    if tracked_product.last_status == "quarantined":
        return "skipped_quarantined"

    if _is_fresh(tracked_product.last_checked_at, now_utc):
        return "skipped_fresh"

    session.add(
        FetchJob(
            tracked_product_id=tracked_product_id,
            reason=reason,
            priority=priority,
            status="queued",
            next_run_at=now_utc.replace(tzinfo=None),
        )
    )
    session.commit()
    return "created"


def _is_fresh(last_checked_at: datetime | None, now: datetime) -> bool:
    if last_checked_at is None:
        return False
    return _as_utc(last_checked_at) >= now - FETCH_JOB_FRESHNESS_WINDOW


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
