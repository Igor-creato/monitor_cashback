from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import FetchJob, NotificationEvent, PriceHistory

MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365
FINISHED_FETCH_JOB_STATUSES = ("done", "failed")


def cleanup_price_history(
    retention_days: int,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> int:
    cutoff = _retention_cutoff(retention_days, now=now)
    return _run_delete(
        delete(PriceHistory).where(PriceHistory.fetched_at < cutoff),
        session=session,
    )


def cleanup_old_fetch_jobs(
    retention_days: int,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> int:
    cutoff = _retention_cutoff(retention_days, now=now)
    return _run_delete(
        delete(FetchJob).where(
            FetchJob.status.in_(FINISHED_FETCH_JOB_STATUSES),
            FetchJob.finished_at < cutoff,
        ),
        session=session,
    )


def cleanup_notification_events(
    retention_days: int,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> int:
    cutoff = _retention_cutoff(retention_days, now=now)
    return _run_delete(
        delete(NotificationEvent).where(NotificationEvent.created_at < cutoff),
        session=session,
    )


def _retention_cutoff(retention_days: int, *, now: datetime | None = None) -> datetime:
    if retention_days < MIN_RETENTION_DAYS or retention_days > MAX_RETENTION_DAYS:
        raise ValueError("retention_days must be between 1 and 365.")

    now_utc = _as_utc(now or datetime.now(UTC))
    return (now_utc - timedelta(days=retention_days)).replace(tzinfo=None)


def _run_delete(statement, *, session: Session | None) -> int:
    if session is not None:
        result = session.execute(statement)
        session.commit()
        return result.rowcount or 0

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        result = owned_session.execute(statement)
        owned_session.commit()
        return result.rowcount or 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
