from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import (
    FetchJob,
    SourceHealthEvent,
    SourceQuarantineState,
    TrackedProduct,
    UserProductSubscription,
)
from app.services.scheduler import (
    SchedulerCostBudget,
    calculate_product_priority,
    schedule_due_fetch_jobs,
    select_products_due_for_check,
)
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserPriceMonitorLimits,
)

NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.fetch_strategy as fetch_strategy
    import app.services.scheduler as scheduler
    import app.services.source_profiles as source_profiles
    import app.services.source_quarantine as source_quarantine

    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(fetch_strategy, "SessionLocal", session_factory)
    monkeypatch.setattr(source_profiles, "SessionLocal", session_factory)
    monkeypatch.setattr(source_quarantine, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _limits(
    external_user_id: str,
    *,
    tariff: str,
    min_fetch_interval_minutes: int,
    browser_fallback_allowed: bool = False,
) -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id=external_user_id,
        tariff=tariff,
        limits=PriceMonitorLimitValues(
            max_tracked_products=100,
            history_days=30,
            min_fetch_interval_minutes=min_fetch_interval_minutes,
            alerts_per_day=10,
            manual_refresh_per_day=5,
            browser_fallback_allowed=browser_fallback_allowed,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0.5"),
            cashback_currency="RUB",
        ),
    )


def _limits_provider(site_id: str, external_user_id: str) -> UserPriceMonitorLimits:
    if external_user_id.startswith("pro"):
        return _limits(
            external_user_id,
            tariff="pro",
            min_fetch_interval_minutes=60,
            browser_fallback_allowed=True,
        )
    return _limits(
        external_user_id,
        tariff="free",
        min_fetch_interval_minutes=360,
    )


def _product(
    session: Session,
    *,
    product_id: int,
    source: str = "testshop",
    last_checked_at: datetime | None = None,
    last_price: Decimal | None = Decimal("1000.00"),
    updated_at: datetime | None = None,
) -> TrackedProduct:
    product = TrackedProduct(
        id=product_id,
        source=source,
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://{source}.local/product/{product_id}",
        region_code="default",
        last_checked_at=(
            last_checked_at.replace(tzinfo=None) if last_checked_at else None
        ),
        last_price=last_price,
        currency="RUB",
        updated_at=(updated_at or NOW).replace(tzinfo=None),
    )
    session.add(product)
    session.commit()
    return product


def _subscription(
    session: Session,
    product: TrackedProduct,
    *,
    external_user_id: str = "free-1",
    target_price: Decimal | None = None,
    is_active: bool = True,
    updated_at: datetime | None = None,
) -> UserProductSubscription:
    subscription = UserProductSubscription(
        site_id="savelloclub.ru",
        external_user_id=external_user_id,
        tracked_product_id=product.id,
        target_price=target_price,
        is_active=is_active,
        updated_at=(updated_at or NOW).replace(tzinfo=None),
    )
    session.add(subscription)
    session.commit()
    session.refresh(product)
    return subscription


def _fetch_job_count(session: Session) -> int:
    return session.scalar(select(func.count(FetchJob.id))) or 0


def test_due_stale_product_gets_queued_job(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=7),
    )
    _subscription(db_session, product)

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    job = db_session.scalar(select(FetchJob))
    assert report.scheduled_count == 1
    assert report.skipped == []
    assert job is not None
    assert job.tracked_product_id == product.id
    assert job.status == "queued"
    assert job.reason == "scheduled"
    assert job.next_run_at == NOW.replace(tzinfo=None)


def test_fresh_product_gets_no_job_and_report_reason(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(minutes=30),
    )
    _subscription(db_session, product, external_user_id="pro-1")

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled == []
    assert report.skipped_count == 1
    assert report.skipped[0].tracked_product_id == product.id
    assert report.skipped[0].reason == "fresh"
    assert _fetch_job_count(db_session) == 0


def test_product_with_many_subscribers_has_higher_priority(
    db_session: Session,
) -> None:
    one = _product(db_session, product_id=1)
    many = _product(db_session, product_id=2)
    _subscription(db_session, one, external_user_id="free-single")
    for index in range(100):
        _subscription(db_session, many, external_user_id=f"free-{index}")

    one_priority = calculate_product_priority(one, now=NOW)
    many_priority = calculate_product_priority(many, now=NOW)

    assert many_priority > one_priority


def test_product_near_target_price_has_higher_priority(
    db_session: Session,
) -> None:
    far = _product(db_session, product_id=1, last_price=Decimal("1000.00"))
    near = _product(db_session, product_id=2, last_price=Decimal("1000.00"))
    _subscription(db_session, far, target_price=Decimal("500.00"))
    _subscription(db_session, near, target_price=Decimal("960.00"))

    assert calculate_product_priority(near, now=NOW) > calculate_product_priority(
        far,
        now=NOW,
    )


def test_quarantined_source_is_skipped(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=7),
    )
    _subscription(db_session, product)
    db_session.add(
        SourceQuarantineState(
            source_code="testshop",
            status="quarantined",
            reason="too_many_403",
            error_type="http_403",
            quarantined_until=(NOW + timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled == []
    assert report.skipped[0].reason == "source_quarantined"
    assert _fetch_job_count(db_session) == 0


def test_existing_queued_job_blocks_duplicate(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=7),
    )
    _subscription(db_session, product)
    db_session.add(
        FetchJob(
            tracked_product_id=product.id,
            status="queued",
            reason="existing",
            next_run_at=NOW.replace(tzinfo=None),
        )
    )
    db_session.commit()

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled == []
    assert report.skipped[0].reason == "active_job_exists"
    assert _fetch_job_count(db_session) == 1


def test_free_only_product_uses_larger_interval(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=2),
    )
    _subscription(db_session, product, external_user_id="free-1")

    candidates = select_products_due_for_check(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert candidates == []


def test_pro_subscriber_shortens_interval(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=2),
    )
    _subscription(db_session, product, external_user_id="free-1")
    _subscription(db_session, product, external_user_id="pro-1")

    candidates = select_products_due_for_check(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert [candidate.tracked_product.id for candidate in candidates] == [product.id]


def test_report_contains_scheduled_items_and_skipped_reasons(
    db_session: Session,
) -> None:
    due = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=7),
    )
    fresh = _product(
        db_session,
        product_id=2,
        last_checked_at=NOW - timedelta(minutes=30),
    )
    _subscription(db_session, due)
    _subscription(db_session, fresh, external_user_id="pro-1")

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled_count == 1
    assert report.scheduled[0].tracked_product_id == due.id
    assert report.skipped_count == 1
    assert report.skipped[0].tracked_product_id == fresh.id
    assert report.skipped[0].reason == "fresh"


def test_many_subscribers_create_single_job_for_one_product(
    db_session: Session,
) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=7),
    )
    for index in range(10):
        _subscription(db_session, product, external_user_id=f"free-{index}")

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled_count == 1
    assert _fetch_job_count(db_session) == 1


def test_inactive_subscriptions_are_ignored(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(hours=7),
    )
    _subscription(db_session, product, is_active=False)

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled == []
    assert report.skipped == []
    assert _fetch_job_count(db_session) == 0


def test_cost_budget_exhaustion_skips_expensive_candidate(
    db_session: Session,
) -> None:
    product = _product(
        db_session,
        product_id=1,
        source="ozon",
        last_checked_at=NOW - timedelta(hours=7),
    )
    _subscription(db_session, product, external_user_id="pro-1")

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
        cost_budget=SchedulerCostBudget(max_cost_units=5),
    )

    assert report.scheduled == []
    assert report.skipped[0].reason == "cost_budget_exceeded"
    assert _fetch_job_count(db_session) == 0


def test_free_only_expensive_source_is_skipped_without_consuming_budget(
    db_session: Session,
) -> None:
    product = _product(
        db_session,
        product_id=1,
        source="ozon",
        last_checked_at=NOW - timedelta(hours=7),
    )
    _subscription(db_session, product, external_user_id="free-1")
    budget = SchedulerCostBudget(max_cost_units=30)

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
        cost_budget=budget,
    )

    assert report.scheduled == []
    assert report.skipped[0].reason == "free_only_expensive_strategy_not_allowed"
    assert report.cost_units_used == 0


def test_recent_bad_source_health_delays_due_product(db_session: Session) -> None:
    product = _product(
        db_session,
        product_id=1,
        last_checked_at=NOW - timedelta(minutes=90),
    )
    _subscription(db_session, product, external_user_id="pro-1")
    db_session.add(
        SourceHealthEvent(
            source_code="testshop",
            event_type="timeout",
            created_at=(NOW - timedelta(minutes=5)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    report = schedule_due_fetch_jobs(
        10,
        session=db_session,
        now=NOW,
        limits_provider=_limits_provider,
    )

    assert report.scheduled == []
    assert report.skipped[0].reason == "fresh"
