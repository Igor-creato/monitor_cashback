from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.cashback_api import CashbackAPIUnavailableError
from app.db import Base
from app.fetchers.base import PriceFetchResult
from app.models.monitoring import (
    FetchAttempt,
    FetchJob,
    PriceHistory,
    TrackedProduct,
    TrackedProductCashback,
)
from app.services.fetch_job_runner import run_http_fetch_job
from app.services.image_storage import StoredImage
from app.services.multistage_fetch_executor import (
    FetchPipelineFailed,
    ProductFetchExecutionContext,
)
from app.services.product_cashback import upsert_product_cashback_snapshot

FETCHED_AT = datetime(2026, 6, 7, 12, 30, tzinfo=UTC)


class FakeFetcher:
    pass


class FakeProductFetchExecutor:
    def __init__(
        self,
        result: PriceFetchResult | Exception,
        *,
        record_attempt: bool = False,
    ) -> None:
        self.result = result
        self.record_attempt = record_attempt
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        tracked_product_id: int,
        context: ProductFetchExecutionContext,
    ) -> PriceFetchResult:
        self.calls.append(
            {
                "tracked_product_id": tracked_product_id,
                "context": context,
            }
        )

        if self.record_attempt:
            product = context.session.get(TrackedProduct, tracked_product_id)
            assert product is not None
            context.attempt_recorder(
                tracked_product_id=tracked_product_id,
                source_code=product.source,
                strategy="direct_http",
                status="success",
                fetch_job_id=context.fetch_job_id,
                worker_name=context.worker_name,
                product_data_found=True,
                price_found=True,
                image_found=True,
                session=context.session,
            )

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
    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        lambda *args, **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "evaluate_price_alerts",
        lambda *args, **kwargs: [],
        raising=False,
    )

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


def _fetch_job(
    session: Session,
    *,
    status: str = "queued",
    worker_name: str | None = None,
) -> FetchJob:
    job = FetchJob(
        id=1,
        tracked_product_id=1,
        status=status,
        reason="scheduled",
        next_run_at=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        error_text="previous error",
        worker_name=worker_name,
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


def _pipeline_failure(error_type: str = "http_429") -> FetchPipelineFailed:
    return FetchPipelineFailed(
        tracked_product_id=1,
        source_code="testshop",
        attempted_strategies=["direct_http"],
        last_error_type=error_type,
    )


def _attempts(session: Session) -> list[FetchAttempt]:
    return list(session.scalars(select(FetchAttempt).order_by(FetchAttempt.id)))


def _price_history_count(session: Session) -> int:
    return session.scalar(select(func.count(PriceHistory.id))) or 0


def test_runner_calls_product_fetch_executor_with_context(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session, worker_name="worker-1")
    fetcher = FakeFetcher()
    executor = FakeProductFetchExecutor(_successful_result())

    def schema_resolver(*_):
        return None

    run_http_fetch_job(
        1,
        fetcher,
        schema_resolver=schema_resolver,
        product_fetch_executor=executor,
    )

    assert len(executor.calls) == 1
    call = executor.calls[0]
    context = call["context"]
    assert call["tracked_product_id"] == 1
    assert context.session.get(TrackedProduct, 1) is not None
    assert context.fetch_job_id == 1
    assert context.worker_name == "worker-1"
    assert context.http_fetcher is fetcher
    assert context.schema_resolver is schema_resolver


def test_successful_executor_result_updates_tracked_product(
    db_session: Session,
) -> None:
    _tracked_product(db_session, fail_count=2)
    _fetch_job(db_session)
    executor = FakeProductFetchExecutor(_successful_result())

    run_http_fetch_job(1, FakeFetcher(), product_fetch_executor=executor)

    product = db_session.get(TrackedProduct, 1)
    assert product is not None
    db_session.refresh(product)
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


def test_successful_executor_result_writes_price_history(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

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


def test_successful_executor_result_marks_job_done(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    job = db_session.get(FetchJob, 1)
    assert job is not None
    db_session.refresh(job)
    assert job.status == "done"
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.error_text is None


def test_image_copy_success_saves_image_object_key(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    def fake_image_store(tracked_product_id, image_url, **kwargs):
        assert tracked_product_id == 1
        assert image_url == "https://testshop.local/images/1.jpg"
        return StoredImage(
            image_url="https://cdn.example.com/products/1/copied.webp",
            object_key="products/1/copied.webp",
            copied=True,
            content_type="image/webp",
            reason=None,
        )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        image_store=fake_image_store,
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    product = db_session.get(TrackedProduct, 1)
    assert product is not None
    db_session.refresh(product)
    assert product.image_object_key == "products/1/copied.webp"
    assert product.image_url == "https://cdn.example.com/products/1/copied.webp"


def test_image_copy_failure_does_not_fail_job_and_keeps_image_url(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    def failing_image_store(*args, **kwargs):
        raise RuntimeError("storage down")

    run_http_fetch_job(
        1,
        FakeFetcher(),
        image_store=failing_image_store,
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    product = db_session.get(TrackedProduct, 1)
    job = db_session.get(FetchJob, 1)
    assert product is not None
    assert job is not None
    db_session.refresh(product)
    db_session.refresh(job)
    assert job.status == "done"
    assert product.last_status == "ok"
    assert product.image_object_key is None
    assert product.image_url == "https://testshop.local/images/1.jpg"
    assert _price_history_count(db_session) == 1


def test_pipeline_failure_marks_job_failed_and_increments_fail_count(
    db_session: Session,
) -> None:
    _tracked_product(db_session, fail_count=2)
    _fetch_job(db_session)

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_pipeline_failure()),
    )

    job = db_session.get(FetchJob, 1)
    product = db_session.get(TrackedProduct, 1)
    assert job is not None
    assert product is not None
    db_session.refresh(job)
    db_session.refresh(product)
    assert job.status == "failed"
    assert job.finished_at is not None
    assert "http_429" in (job.error_text or "")
    assert product.fail_count == 3
    assert product.last_status == "http_429"
    assert _price_history_count(db_session) == 0


def test_pipeline_failure_does_not_call_cashback_or_alerts(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    cashback_calls = []
    alert_calls = []

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        lambda *args, **kwargs: cashback_calls.append((args, kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "evaluate_price_alerts",
        lambda *args, **kwargs: alert_calls.append((args, kwargs)),
        raising=False,
    )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(
            _pipeline_failure("price_not_found")
        ),
    )

    job = db_session.get(FetchJob, 1)
    assert job is not None
    db_session.refresh(job)
    assert job.status == "failed"
    assert cashback_calls == []
    assert alert_calls == []


def test_successful_job_calls_cashback_resolver(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    calls = []

    def fake_resolver(tracked_product_id, *, price, currency, region_code, session):
        calls.append(
            {
                "tracked_product_id": tracked_product_id,
                "price": price,
                "currency": currency,
                "region_code": region_code,
                "session": session,
            }
        )
        return None

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        fake_resolver,
        raising=False,
    )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    assert len(calls) == 1
    assert calls[0]["tracked_product_id"] == 1
    assert calls[0]["price"] == Decimal("1499.90")
    assert calls[0]["currency"] == "RUB"
    assert calls[0]["region_code"] == "default"
    assert calls[0]["session"].get(TrackedProduct, 1) is not None


def test_successful_job_evaluates_price_alerts(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    calls = []

    def fake_evaluate_price_alerts(tracked_product_id):
        calls.append(tracked_product_id)
        return []

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "evaluate_price_alerts",
        fake_evaluate_price_alerts,
        raising=False,
    )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    assert calls == [1]


def test_cashback_api_error_does_not_fail_successful_fetch_job(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    def failing_resolver(*args, **kwargs):
        raise CashbackAPIUnavailableError("Cashback API is unavailable.")

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        failing_resolver,
        raising=False,
    )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    job = db_session.get(FetchJob, 1)
    product = db_session.get(TrackedProduct, 1)
    assert job is not None
    assert product is not None
    db_session.refresh(job)
    db_session.refresh(product)
    assert job.status == "done"
    assert product.last_status == "ok"
    assert _price_history_count(db_session) == 1


def test_successful_job_persists_no_partner_cashback_snapshot(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    def no_partner_resolver(tracked_product_id, *, session, **kwargs):
        return upsert_product_cashback_snapshot(
            tracked_product_id,
            {
                "cashback_status": "no_partner",
                "confidence": "none",
                "display_policy": "cashback_unavailable",
            },
            session=session,
        )

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        no_partner_resolver,
        raising=False,
    )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    snapshot = db_session.scalar(select(TrackedProductCashback))
    assert snapshot is not None
    assert snapshot.cashback_status == "no_partner"
    assert snapshot.confidence == "none"
    assert snapshot.display_policy == "cashback_unavailable"


def test_successful_job_persists_partner_estimated_cashback_snapshot(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    def partner_estimated_resolver(tracked_product_id, *, session, **kwargs):
        return upsert_product_cashback_snapshot(
            tracked_product_id,
            {
                "cashback_status": "partner_estimated",
                "commission_rate_type": "percent",
                "commission_min": "5",
                "commission_max": "12",
                "user_share": "0.5",
                "expected_cashback_min": "37.50",
                "expected_cashback_max": "90.00",
                "effective_price_conservative": "1462.40",
                "confidence": "medium",
                "display_policy": "show_range_use_min_for_effective_price",
            },
            session=session,
        )

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        partner_estimated_resolver,
        raising=False,
    )

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(_successful_result()),
    )

    snapshot = db_session.scalar(select(TrackedProductCashback))
    assert snapshot is not None
    assert snapshot.cashback_status == "partner_estimated"
    assert snapshot.expected_cashback_min == Decimal("37.50")
    assert snapshot.expected_cashback_max == Decimal("90.00")
    assert snapshot.effective_price_conservative == Decimal("1462.40")
    assert snapshot.display_policy == "show_range_use_min_for_effective_price"


def test_fetch_attempt_is_saved_by_executor_without_runner_duplicate(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session, worker_name="worker-1")

    run_http_fetch_job(
        1,
        FakeFetcher(),
        product_fetch_executor=FakeProductFetchExecutor(
            _successful_result(),
            record_attempt=True,
        ),
    )

    attempts = _attempts(db_session)
    assert len(attempts) == 1
    assert attempts[0].status == "success"
    assert attempts[0].fetch_job_id == 1
    assert attempts[0].tracked_product_id == 1
    assert attempts[0].source_code == "testshop"
    assert attempts[0].strategy == "direct_http"
    assert attempts[0].worker_name == "worker-1"
    assert attempts[0].product_data_found is True
    assert attempts[0].price_found is True
    assert attempts[0].image_found is True


def test_done_job_is_not_fetched_twice(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session, status="done")
    executor = FakeProductFetchExecutor(_successful_result())

    run_http_fetch_job(1, FakeFetcher(), product_fetch_executor=executor)

    assert executor.calls == []
    assert _price_history_count(db_session) == 0


def test_missing_job_is_safe(db_session: Session) -> None:
    _tracked_product(db_session)
    executor = FakeProductFetchExecutor(_successful_result())

    run_http_fetch_job(999, FakeFetcher(), product_fetch_executor=executor)

    assert executor.calls == []
    assert _price_history_count(db_session) == 0
