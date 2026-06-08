from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import (
    FetchJob,
    NotificationEvent,
    PriceHistory,
    TrackedProduct,
    UserProductSubscription,
)
from app.services.cleanup import (
    cleanup_notification_events,
    cleanup_old_fetch_jobs,
    cleanup_price_history,
)


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


def _tracked_product(session: Session) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=1,
        source="testshop",
        external_product_id="sku-1",
        canonical_url="https://testshop.local/product/1",
        region_code="default",
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _subscription(session: Session) -> UserProductSubscription:
    subscription = UserProductSubscription(
        id=1,
        site_id="site-1",
        external_user_id="user-1",
        tracked_product_id=1,
    )
    session.add(subscription)
    session.commit()
    return subscription


def _price_history_count(session: Session) -> int:
    return session.scalar(select(func.count(PriceHistory.id))) or 0


def _fetch_job_count(session: Session) -> int:
    return session.scalar(select(func.count(FetchJob.id))) or 0


def _notification_event_count(session: Session) -> int:
    return session.scalar(select(func.count(NotificationEvent.id))) or 0


def test_old_price_history_is_deleted(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    db_session.add(
        PriceHistory(
            tracked_product_id=1,
            price_current=Decimal("1000.00"),
            currency="RUB",
            availability=True,
            fetched_at=(now - timedelta(days=31)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    deleted_count = cleanup_price_history(30, session=db_session, now=now)

    assert deleted_count == 1
    assert _price_history_count(db_session) == 0


def test_fresh_price_history_remains(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    db_session.add(
        PriceHistory(
            tracked_product_id=1,
            price_current=Decimal("1000.00"),
            currency="RUB",
            availability=True,
            fetched_at=(now - timedelta(days=29)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    deleted_count = cleanup_price_history(30, session=db_session, now=now)

    assert deleted_count == 0
    assert _price_history_count(db_session) == 1


def test_old_done_fetch_jobs_are_deleted(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    db_session.add(
        FetchJob(
            tracked_product_id=1,
            status="done",
            next_run_at=now.replace(tzinfo=None),
            finished_at=(now - timedelta(days=31)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    deleted_count = cleanup_old_fetch_jobs(30, session=db_session, now=now)

    assert deleted_count == 1
    assert _fetch_job_count(db_session) == 0


def test_running_and_queued_fetch_jobs_are_not_deleted(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    for job_id, status in enumerate(("queued", "running"), start=1):
        db_session.add(
            FetchJob(
                id=job_id,
                tracked_product_id=1,
                status=status,
                next_run_at=now.replace(tzinfo=None),
                finished_at=(now - timedelta(days=31)).replace(tzinfo=None),
            )
        )
    db_session.commit()

    deleted_count = cleanup_old_fetch_jobs(30, session=db_session, now=now)

    assert deleted_count == 0
    assert _fetch_job_count(db_session) == 2


def test_old_notification_events_are_deleted(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    _tracked_product(db_session)
    _subscription(db_session)
    db_session.add(
        NotificationEvent(
            site_id="site-1",
            external_user_id="user-1",
            subscription_id=1,
            tracked_product_id=1,
            event_type="target_price_reached",
            status="pending",
            payload_json="{}",
            created_at=(now - timedelta(days=31)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    deleted_count = cleanup_notification_events(30, session=db_session, now=now)

    assert deleted_count == 1
    assert _notification_event_count(db_session) == 0


@pytest.mark.parametrize(
    "cleanup_func",
    [
        cleanup_price_history,
        cleanup_old_fetch_jobs,
        cleanup_notification_events,
    ],
)
def test_retention_days_below_one_is_rejected(cleanup_func) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        cleanup_func(0, session=None)


@pytest.mark.parametrize(
    "cleanup_func",
    [
        cleanup_price_history,
        cleanup_old_fetch_jobs,
        cleanup_notification_events,
    ],
)
def test_retention_days_above_365_is_rejected(cleanup_func) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        cleanup_func(366, session=None)
