from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.fetchers.base import FetchError, PriceFetchResult
from app.models.monitoring import FetchJob, PriceHistory, TrackedProduct
from app.services.fetch_job_runner import run_http_fetch_job

FETCHED_AT = datetime(2026, 6, 7, 12, 30, tzinfo=UTC)


class FakeFetcher:
    def __init__(self, result: PriceFetchResult | Exception) -> None:
        self.result = result
        self.urls: list[str] = []

    def fetch(self, url: str) -> PriceFetchResult:
        self.urls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(runner, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _tracked_product(session: Session, *, fail_count: int = 0) -> TrackedProduct:
    tracked_product = TrackedProduct(
        id=1,
        source="testshop",
        external_product_id="sku-1",
        canonical_url="https://testshop.local/product/1",
        region_code="default",
        product_name="Old name",
        last_price=Decimal("999.00"),
        last_old_price=None,
        currency="RUB",
        last_availability=True,
        fail_count=fail_count,
        last_status="old_status",
    )
    session.add(tracked_product)
    session.commit()
    return tracked_product


def _fetch_job(session: Session, *, status: str = "queued") -> FetchJob:
    job = FetchJob(
        id=1,
        tracked_product_id=1,
        status=status,
        reason="scheduled",
        next_run_at=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        error_text="previous error",
    )
    session.add(job)
    session.commit()
    return job


def _successful_result() -> PriceFetchResult:
    return PriceFetchResult(
        product_name="Fresh phone",
        price_current=Decimal("1499.90"),
        price_old=Decimal("1999.00"),
        currency="RUB",
        availability=False,
        seller_name="Test Seller",
        image_url="https://testshop.local/images/1.jpg",
        fetched_at=FETCHED_AT,
    )


def _price_history_count(session: Session) -> int:
    return session.scalar(select(func.count(PriceHistory.id))) or 0


def test_successful_job_updates_tracked_product(db_session: Session) -> None:
    _tracked_product(db_session, fail_count=2)
    _fetch_job(db_session)
    fetcher = FakeFetcher(_successful_result())

    run_http_fetch_job(1, fetcher)

    product = db_session.get(TrackedProduct, 1)
    assert product is not None
    db_session.refresh(product)
    assert fetcher.urls == ["https://testshop.local/product/1"]
    assert product.product_name == "Fresh phone"
    assert product.last_price == Decimal("1499.90")
    assert product.last_old_price == Decimal("1999.00")
    assert product.currency == "RUB"
    assert product.last_availability is False
    assert product.image_url == "https://testshop.local/images/1.jpg"
    assert product.last_checked_at == FETCHED_AT.replace(tzinfo=None)
    assert product.last_success_at == FETCHED_AT.replace(tzinfo=None)
    assert product.last_status == "ok"
    assert product.fail_count == 0


def test_successful_job_writes_price_history(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    run_http_fetch_job(1, FakeFetcher(_successful_result()))

    history = db_session.scalar(select(PriceHistory))
    assert history is not None
    assert history.tracked_product_id == 1
    assert history.price_current == Decimal("1499.90")
    assert history.price_old == Decimal("1999.00")
    assert history.currency == "RUB"
    assert history.availability is False
    assert history.seller_name == "Test Seller"
    assert history.fetched_at == FETCHED_AT.replace(tzinfo=None)
    assert _price_history_count(db_session) == 1


def test_successful_job_marks_job_done(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    run_http_fetch_job(1, FakeFetcher(_successful_result()))

    job = db_session.get(FetchJob, 1)
    assert job is not None
    db_session.refresh(job)
    assert job.status == "done"
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.error_text is None


def test_fetch_error_marks_job_failed(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    run_http_fetch_job(1, FakeFetcher(FetchError("http_429", "too many requests")))

    job = db_session.get(FetchJob, 1)
    assert job is not None
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.finished_at is not None
    assert "http_429" in (job.error_text or "")
    assert "too many requests" in (job.error_text or "")


def test_fetch_error_increments_product_fail_count(db_session: Session) -> None:
    _tracked_product(db_session, fail_count=2)
    _fetch_job(db_session)

    run_http_fetch_job(1, FakeFetcher(FetchError("http_429", "too many requests")))

    product = db_session.get(TrackedProduct, 1)
    assert product is not None
    db_session.refresh(product)
    assert product.fail_count == 3
    assert product.last_status == "http_429"


def test_done_job_is_not_fetched_twice(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session, status="done")
    fetcher = FakeFetcher(_successful_result())

    run_http_fetch_job(1, fetcher)

    assert fetcher.urls == []
    assert _price_history_count(db_session) == 0


def test_missing_job_is_safe(db_session: Session) -> None:
    _tracked_product(db_session)
    fetcher = FakeFetcher(_successful_result())

    run_http_fetch_job(999, fetcher)

    assert fetcher.urls == []
    assert _price_history_count(db_session) == 0
