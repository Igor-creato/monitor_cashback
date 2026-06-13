from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import FetchAttempt, FetchJob, TrackedProduct
from app.services.fetch_attempts import (
    get_cost_per_success,
    get_strategy_success_rate,
    record_fetch_attempt,
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


def _tracked_product(
    session: Session,
    *,
    product_id: int = 1,
) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=product_id,
        source="testshop",
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://testshop.local/product/{product_id}",
        region_code="default",
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _fetch_job(
    session: Session,
    *,
    job_id: int = 1,
    tracked_product_id: int = 1,
    now: datetime | None = None,
) -> FetchJob:
    now = now or datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    job = FetchJob(
        id=job_id,
        tracked_product_id=tracked_product_id,
        status="running",
        next_run_at=now.replace(tzinfo=None),
    )
    session.add(job)
    session.commit()
    return job


def _insert_attempt(
    session: Session,
    *,
    source_code: str = "wildberries",
    strategy: str = "direct_http",
    status: str = "success",
    tracked_product_id: int = 1,
    cost_estimated: Decimal | None = None,
    created_at: datetime | None = None,
) -> FetchAttempt:
    """Прямая вставка attempt с явным created_at для детерминированных агрегатов."""
    attempt = FetchAttempt(
        tracked_product_id=tracked_product_id,
        source_code=source_code,
        strategy=strategy,
        status=status,
        cost_estimated=cost_estimated,
    )
    if created_at is not None:
        attempt.created_at = created_at.replace(tzinfo=None)
    session.add(attempt)
    session.commit()
    return attempt


def _attempt_count(session: Session) -> int:
    return session.scalar(select(func.count(FetchAttempt.id))) or 0


def test_success_attempt_recorded(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    attempt = record_fetch_attempt(
        tracked_product_id=1,
        source_code="wildberries",
        strategy="direct_http",
        status="success",
        fetch_job_id=1,
        worker_name="worker-1",
        http_status=200,
        response_ms=345,
        bytes_downloaded=10240,
        product_data_found=True,
        price_found=True,
        image_found=True,
        session=db_session,
    )

    assert attempt.id is not None
    assert attempt.status == "success"
    assert attempt.source_code == "wildberries"
    assert attempt.strategy == "direct_http"
    assert attempt.fetch_job_id == 1
    assert attempt.http_status == 200
    assert attempt.response_ms == 345
    assert attempt.error_type is None
    assert _attempt_count(db_session) == 1


def test_failed_attempt_recorded_with_error_type(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    attempt = record_fetch_attempt(
        tracked_product_id=1,
        source_code="ozon",
        strategy="standard_proxy_http",
        status="failed",
        fetch_job_id=1,
        error_type="http_403",
        http_status=403,
        response_ms=512,
        session=db_session,
    )

    assert attempt.status == "failed"
    assert attempt.error_type == "http_403"
    assert attempt.http_status == 403
    assert attempt.price_found is False
    assert attempt.image_found is False
    assert _attempt_count(db_session) == 1


def test_cost_per_success_computed(db_session: Session) -> None:
    _tracked_product(db_session)
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    recent = now - timedelta(hours=1)

    # 2 успеха + 2 провала, у всех есть оценочная стоимость.
    _insert_attempt(
        db_session, status="success", cost_estimated=Decimal("0.50"), created_at=recent
    )
    _insert_attempt(
        db_session, status="success", cost_estimated=Decimal("0.30"), created_at=recent
    )
    _insert_attempt(
        db_session, status="failed", cost_estimated=Decimal("0.10"), created_at=recent
    )
    _insert_attempt(
        db_session, status="failed", cost_estimated=Decimal("0.10"), created_at=recent
    )

    # SUM(всех cost) / COUNT(success) = (0.50+0.30+0.10+0.10) / 2 = 0.50
    cost = get_cost_per_success(
        "wildberries", timedelta(days=1), now=now, session=db_session
    )

    assert cost == Decimal("0.50")


def test_cost_per_success_returns_zero_without_successes(db_session: Session) -> None:
    _tracked_product(db_session)
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    _insert_attempt(
        db_session,
        status="failed",
        cost_estimated=Decimal("0.40"),
        created_at=now - timedelta(hours=1),
    )

    cost = get_cost_per_success(
        "wildberries", timedelta(days=1), now=now, session=db_session
    )

    assert cost == Decimal("0")


def test_strategy_success_rate_computed(db_session: Session) -> None:
    _tracked_product(db_session)
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    recent = now - timedelta(hours=1)

    # 3 success + 1 failed для (wildberries, direct_http) => 0.75
    for _ in range(3):
        _insert_attempt(
            db_session, strategy="direct_http", status="success", created_at=recent
        )
    _insert_attempt(
        db_session, strategy="direct_http", status="failed", created_at=recent
    )
    # Шум: другая стратегия и другой source не должны влиять.
    _insert_attempt(
        db_session, strategy="standard_proxy_http", status="failed", created_at=recent
    )
    _insert_attempt(
        db_session,
        source_code="ozon",
        strategy="direct_http",
        status="failed",
        created_at=recent,
    )

    rate = get_strategy_success_rate(
        "wildberries", "direct_http", timedelta(days=1), now=now, session=db_session
    )

    assert rate == pytest.approx(0.75)


def test_strategy_success_rate_excludes_attempts_outside_period(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)

    # Внутри окна: 1 success.
    _insert_attempt(
        db_session,
        strategy="direct_http",
        status="success",
        created_at=now - timedelta(hours=1),
    )
    # Вне окна (старше суток): provider failed, не должен учитываться.
    _insert_attempt(
        db_session,
        strategy="direct_http",
        status="failed",
        created_at=now - timedelta(days=2),
    )

    rate = get_strategy_success_rate(
        "wildberries", "direct_http", timedelta(days=1), now=now, session=db_session
    )

    assert rate == pytest.approx(1.0)


def test_strategy_success_rate_zero_when_no_attempts(db_session: Session) -> None:
    _tracked_product(db_session)
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)

    rate = get_strategy_success_rate(
        "wildberries", "direct_http", timedelta(days=1), now=now, session=db_session
    )

    assert rate == 0.0


def test_price_found_and_image_found_persisted(db_session: Session) -> None:
    _tracked_product(db_session)

    attempt = record_fetch_attempt(
        tracked_product_id=1,
        source_code="wildberries",
        strategy="direct_http",
        status="success",
        product_data_found=True,
        price_found=True,
        image_found=False,
        session=db_session,
    )

    db_session.expire(attempt)
    reloaded = db_session.get(FetchAttempt, attempt.id)
    assert reloaded is not None
    assert reloaded.product_data_found is True
    assert reloaded.price_found is True
    assert reloaded.image_found is False


def test_attempt_has_no_secret_or_proxy_password(db_session: Session) -> None:
    _tracked_product(db_session)

    attempt = record_fetch_attempt(
        tracked_product_id=1,
        source_code="wildberries",
        strategy="cheap_proxy_http",
        status="success",
        proxy_pool_id=7,
        proxy_endpoint_id=42,
        session=db_session,
    )

    # В схеме не должно быть колонок с секретами/паролями/токенами/credentials.
    column_names = {column.name for column in FetchAttempt.__table__.columns}
    forbidden_substrings = ("password", "secret", "token", "credential", "auth")
    for name in column_names:
        assert not any(bad in name.lower() for bad in forbidden_substrings), name

    # Прокси хранится только как числовые id, не как endpoint-строка/credential.
    assert attempt.proxy_pool_id == 7
    assert attempt.proxy_endpoint_id == 42
    assert isinstance(attempt.proxy_pool_id, int)
    assert isinstance(attempt.proxy_endpoint_id, int)


def test_invalid_status_rejected(db_session: Session) -> None:
    _tracked_product(db_session)

    with pytest.raises(ValueError):
        record_fetch_attempt(
            tracked_product_id=1,
            source_code="wildberries",
            strategy="direct_http",
            status="not_a_real_status",
            session=db_session,
        )
