from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import FetchJob, TrackedProduct
from app.services.fetch_job_dispatcher import dispatch_queued_fetch_jobs

NOW = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)


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


def _product(session: Session, product_id: int) -> TrackedProduct:
    product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://testshop.local/product/{product_id}",
        region_code="default",
    )
    session.add(product)
    session.commit()
    return product


def _job(
    session: Session,
    *,
    job_id: int,
    product_id: int,
    status: str = "queued",
    next_run_at: datetime | None = None,
    priority: int = 5,
) -> None:
    session.add(
        FetchJob(
            id=job_id,
            tracked_product_id=product_id,
            status=status,
            reason="test",
            next_run_at=(next_run_at or NOW).replace(tzinfo=None),
            priority=priority,
        )
    )
    session.commit()


def test_dispatches_due_queued_jobs_in_priority_order(db_session: Session) -> None:
    _product(db_session, 1)
    _product(db_session, 2)
    dispatched: list[int] = []
    _job(db_session, job_id=1, product_id=1, priority=1)
    _job(db_session, job_id=2, product_id=2, priority=9)

    report = dispatch_queued_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        dispatcher=dispatched.append,
    )

    assert report.dispatched_job_ids == [2, 1]
    assert dispatched == [2, 1]


def test_dispatcher_ignores_future_and_non_queued_jobs(db_session: Session) -> None:
    _product(db_session, 1)
    _product(db_session, 2)
    _job(db_session, job_id=1, product_id=1, next_run_at=NOW + timedelta(minutes=5))
    _job(db_session, job_id=2, product_id=2, status="running")
    dispatched: list[int] = []

    report = dispatch_queued_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        dispatcher=dispatched.append,
    )

    assert report.dispatched_job_ids == []
    assert dispatched == []


def test_dispatcher_respects_limit(db_session: Session) -> None:
    _product(db_session, 1)
    _product(db_session, 2)
    _job(db_session, job_id=1, product_id=1)
    _job(db_session, job_id=2, product_id=2)
    dispatched: list[int] = []

    report = dispatch_queued_fetch_jobs(
        1,
        session=db_session,
        now=NOW,
        dispatcher=dispatched.append,
    )

    assert report.dispatched_job_ids == [1]
    assert dispatched == [1]
