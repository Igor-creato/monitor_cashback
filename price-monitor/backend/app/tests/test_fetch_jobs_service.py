from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import FetchJob, TrackedProduct
from app.services.fetch_jobs import enqueue_fetch_job


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


def _tracked_product(
    session: Session,
    *,
    product_id: int = 1,
    last_checked_at: datetime | None = None,
    last_status: str | None = None,
) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://testshop.local/product/{product_id}",
        region_code="default",
        last_checked_at=last_checked_at,
        last_status=last_status,
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _fetch_job_count(session: Session) -> int:
    return session.scalar(select(func.count(FetchJob.id))) or 0


def test_first_enqueue_creates_queued_job(db_session: Session) -> None:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)

    result = enqueue_fetch_job(
        db_session,
        1,
        "watchlist_created",
        priority=3,
        now=now,
    )

    job = db_session.scalar(select(FetchJob))
    assert result == "created"
    assert job is not None
    assert job.tracked_product_id == 1
    assert job.reason == "watchlist_created"
    assert job.priority == 3
    assert job.status == "queued"
    assert job.next_run_at.replace(tzinfo=UTC) == now
    assert _fetch_job_count(db_session) == 1


def test_repeated_enqueue_does_not_create_duplicate_queued_job(
    db_session: Session,
) -> None:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    db_session.add(
        FetchJob(
            tracked_product_id=1,
            status="queued",
            reason="existing",
            next_run_at=now,
        )
    )
    db_session.commit()

    result = enqueue_fetch_job(db_session, 1, "manual_retry", now=now)

    assert result == "existing"
    assert _fetch_job_count(db_session) == 1


def test_running_job_blocks_new_enqueue(db_session: Session) -> None:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    db_session.add(
        FetchJob(
            tracked_product_id=1,
            status="running",
            reason="worker",
            next_run_at=now,
        )
    )
    db_session.commit()

    result = enqueue_fetch_job(db_session, 1, "manual_retry", now=now)

    assert result == "existing"
    assert _fetch_job_count(db_session) == 1


def test_fresh_last_checked_at_skips_job(db_session: Session) -> None:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    _tracked_product(db_session, last_checked_at=now - timedelta(minutes=30))

    result = enqueue_fetch_job(db_session, 1, "watchlist_created", now=now)

    assert result == "skipped_fresh"
    assert _fetch_job_count(db_session) == 0


def test_stale_product_gets_job(db_session: Session) -> None:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    _tracked_product(db_session, last_checked_at=now - timedelta(minutes=61))

    result = enqueue_fetch_job(db_session, 1, "scheduled", now=now)

    assert result == "created"
    assert _fetch_job_count(db_session) == 1


def test_quarantined_product_skips_job(db_session: Session) -> None:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    _tracked_product(db_session, last_status="quarantined")

    result = enqueue_fetch_job(db_session, 1, "scheduled", now=now)

    assert result == "skipped_quarantined"
    assert _fetch_job_count(db_session) == 0
