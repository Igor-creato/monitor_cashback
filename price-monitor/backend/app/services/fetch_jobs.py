from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import FetchJob, TrackedProduct

logger = logging.getLogger(__name__)

FETCH_JOB_ACTIVE_STATUSES = ("queued", "running")
FETCH_JOB_FRESHNESS_WINDOW = timedelta(minutes=60)


def enqueue_fetch_job(
    session: Session,
    tracked_product_id,
    reason,
    priority=5,
    *,
    now: datetime | None = None,
    job_dispatcher: Callable[[int], None] | None = None,
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

    job = FetchJob(
        tracked_product_id=tracked_product_id,
        reason=reason,
        priority=priority,
        status="queued",
        next_run_at=now_utc.replace(tzinfo=None),
    )
    session.add(job)
    session.flush()
    job_id = int(job.id)
    session.commit()
    if job_dispatcher is not None:
        try:
            job_dispatcher(job_id)
        except Exception:
            logger.exception(
                "fetch_job_dispatch_failed",
                extra={"fetch_job_id": job_id},
            )
    return "created"


def _is_fresh(last_checked_at: datetime | None, now: datetime) -> bool:
    if last_checked_at is None:
        return False
    return _as_utc(last_checked_at) >= now - FETCH_JOB_FRESHNESS_WINDOW


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
