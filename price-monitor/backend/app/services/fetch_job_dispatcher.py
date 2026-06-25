from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import FetchJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchJobDispatchReport:
    dispatched_job_ids: list[int]

    @property
    def dispatched_count(self) -> int:
        return len(self.dispatched_job_ids)


def dispatch_queued_fetch_jobs(
    limit: int,
    *,
    session: Session | None = None,
    now: datetime | None = None,
    dispatcher: Callable[[int], None] | None = None,
) -> FetchJobDispatchReport:
    now_utc = _as_utc(now or datetime.now(UTC))
    active_dispatcher = dispatcher or dispatch_fetch_job

    if session is not None:
        return _dispatch_queued_fetch_jobs(
            limit,
            session,
            now=now_utc,
            dispatcher=active_dispatcher,
        )

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _dispatch_queued_fetch_jobs(
            limit,
            owned_session,
            now=now_utc,
            dispatcher=active_dispatcher,
        )


def dispatch_fetch_job(job_id: int) -> None:
    from app.tasks.http_fetch import http_fetch_job

    http_fetch_job.delay(job_id)


def _dispatch_queued_fetch_jobs(
    limit: int,
    session: Session,
    *,
    now: datetime,
    dispatcher: Callable[[int], None],
) -> FetchJobDispatchReport:
    job_ids = list(session.scalars(_queued_jobs_query(limit, now=now)))
    dispatched: list[int] = []
    for job_id in job_ids:
        try:
            dispatcher(int(job_id))
        except Exception:
            logger.exception(
                "queued_fetch_job_dispatch_failed",
                extra={"fetch_job_id": int(job_id)},
            )
            continue
        dispatched.append(int(job_id))

    return FetchJobDispatchReport(dispatched_job_ids=dispatched)


def _queued_jobs_query(limit: int, *, now: datetime) -> Select[tuple[int]]:
    return (
        select(FetchJob.id)
        .where(
            FetchJob.status == "queued",
            or_(
                FetchJob.next_run_at.is_(None),
                FetchJob.next_run_at <= now.replace(tzinfo=None),
            ),
        )
        .order_by(FetchJob.priority.desc(), FetchJob.id.asc())
        .limit(max(0, int(limit)))
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
