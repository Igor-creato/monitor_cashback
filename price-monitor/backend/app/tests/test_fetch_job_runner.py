from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.cashback_api import CashbackAPIUnavailableError
from app.db import Base
from app.extraction import ExtractionSchema
from app.fetchers.base import FetchedPage, FetchError, PriceFetchResult
from app.models.monitoring import (
    FetchAttempt,
    FetchJob,
    PriceHistory,
    TrackedProduct,
    TrackedProductCashback,
)
from app.services.fetch_job_runner import run_http_fetch_job
from app.services.image_storage import StoredImage
from app.services.product_cashback import upsert_product_cashback_snapshot

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


class FakePageFetcher:
    def __init__(self, page: FetchedPage | Exception) -> None:
        self.page = page
        self.urls: list[str] = []

    def fetch_page(self, url: str) -> FetchedPage:
        self.urls.append(url)
        if isinstance(self.page, Exception):
            raise self.page
        return self.page

    def fetch(self, url: str) -> PriceFetchResult:
        raise AssertionError("schema-based runner must use fetch_page")


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


def _json_page(payload: str) -> FetchedPage:
    return FetchedPage(
        content=payload,
        content_type="application/json",
        fetched_at=FETCHED_AT,
        http_status=200,
        response_ms=123,
        bytes_downloaded=len(payload.encode()),
    )


def _html_page(payload: str) -> FetchedPage:
    return FetchedPage(
        content=payload,
        content_type="text/html; charset=utf-8",
        fetched_at=FETCHED_AT,
        http_status=200,
        response_ms=234,
        bytes_downloaded=len(payload.encode()),
    )


def _json_schema(*, price_path: str = "product.price.current") -> ExtractionSchema:
    return ExtractionSchema(
        source_code="testshop",
        version="json-v1",
        content_type="json",
        title_path="product.title",
        price_path=price_path,
        old_price_path="product.price.old",
        currency_path="product.price.currency",
        image_path="product.image",
        availability_path="product.availability",
        seller_path="product.seller",
        required_fields=["price_current"],
    )


def _html_schema() -> ExtractionSchema:
    return ExtractionSchema(
        source_code="testshop",
        version="html-v1",
        content_type="html",
        css_title=".product-title",
        css_price=".price",
        css_old_price=".old-price",
        css_image=".product-image",
        css_availability=".availability",
        required_fields=["title", "price_current"],
    )


def _json_product_payload(*, price: str | None = "1499.90") -> str:
    price_value = "null" if price is None else f'"{price}"'
    return f"""
    {{
      "product": {{
        "title": "Schema Phone",
        "price": {{
          "current": {price_value},
          "old": "1999.00",
          "currency": "RUB"
        }},
        "image": "https://testshop.local/images/schema-phone.jpg",
        "availability": "in_stock",
        "seller": "Schema Seller"
      }}
    }}
    """


def _html_product_payload() -> str:
    return """
    <html>
      <body>
        <article>
          <h1 class="product-title">Schema Coat</h1>
          <span class="price">809,70 ₽</span>
          <span class="old-price">999,00 ₽</span>
          <img class="product-image" src="https://testshop.local/images/coat.jpg" />
          <span class="availability">available</span>
        </article>
      </body>
    </html>
    """


def _attempts(session: Session) -> list[FetchAttempt]:
    return list(session.scalars(select(FetchAttempt).order_by(FetchAttempt.id)))


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


def test_json_extraction_updates_title_price_image_and_history(
    db_session: Session,
) -> None:
    _tracked_product(db_session, fail_count=2)
    _fetch_job(db_session)
    fetcher = FakePageFetcher(_json_page(_json_product_payload()))

    run_http_fetch_job(1, fetcher, schema_resolver=lambda *_: _json_schema())

    product = db_session.get(TrackedProduct, 1)
    history = db_session.scalar(select(PriceHistory))
    assert product is not None
    assert history is not None
    db_session.refresh(product)
    assert fetcher.urls == ["https://testshop.local/product/1"]
    assert product.product_name == "Schema Phone"
    assert product.last_price == Decimal("1499.90")
    assert product.last_old_price == Decimal("1999.00")
    assert product.currency == "RUB"
    assert product.last_availability is True
    assert product.image_url == "https://testshop.local/images/schema-phone.jpg"
    assert product.last_checked_at == FETCHED_AT.replace(tzinfo=None)
    assert product.last_status == "ok"
    assert product.fail_count == 0
    assert history.price_current == Decimal("1499.90")
    assert history.seller_name == "Schema Seller"


def test_html_extraction_updates_title_price_image_and_history(
    db_session: Session,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    fetcher = FakePageFetcher(_html_page(_html_product_payload()))

    run_http_fetch_job(1, fetcher, schema_resolver=lambda *_: _html_schema())

    product = db_session.get(TrackedProduct, 1)
    history = db_session.scalar(select(PriceHistory))
    assert product is not None
    assert history is not None
    db_session.refresh(product)
    assert product.product_name == "Schema Coat"
    assert product.last_price == Decimal("809.70")
    assert product.last_old_price == Decimal("999.00")
    assert product.currency == "RUB"
    assert product.last_availability is True
    assert product.image_url == "https://testshop.local/images/coat.jpg"
    assert history.price_current == Decimal("809.70")


def test_image_copy_success_saves_image_object_key(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    def fake_image_store(tracked_product_id, image_url, **kwargs):
        assert tracked_product_id == 1
        assert image_url == "https://testshop.local/images/schema-phone.jpg"
        return StoredImage(
            image_url="https://cdn.example.com/products/1/copied.webp",
            object_key="products/1/copied.webp",
            copied=True,
            content_type="image/webp",
            reason=None,
        )

    run_http_fetch_job(
        1,
        FakePageFetcher(_json_page(_json_product_payload())),
        schema_resolver=lambda *_: _json_schema(),
        image_store=fake_image_store,
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
        FakePageFetcher(_json_page(_json_product_payload())),
        schema_resolver=lambda *_: _json_schema(),
        image_store=failing_image_store,
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
    assert product.image_url == "https://testshop.local/images/schema-phone.jpg"
    assert _price_history_count(db_session) == 1


def test_missing_extracted_price_fails_job_without_history_or_alerts(
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
        FakePageFetcher(_json_page(_json_product_payload(price=None))),
        schema_resolver=lambda *_: _json_schema(price_path="product.price.current"),
    )

    job = db_session.get(FetchJob, 1)
    product = db_session.get(TrackedProduct, 1)
    assert job is not None
    assert product is not None
    db_session.refresh(job)
    db_session.refresh(product)
    assert job.status == "failed"
    assert "price_not_found" in (job.error_text or "")
    assert product.last_status == "price_not_found"
    assert product.fail_count == 1
    assert _price_history_count(db_session) == 0
    assert cashback_calls == []
    assert alert_calls == []


def test_fetch_attempt_records_extraction_flags(db_session: Session) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)

    run_http_fetch_job(
        1,
        FakePageFetcher(_json_page(_json_product_payload())),
        schema_resolver=lambda *_: _json_schema(),
    )

    attempts = _attempts(db_session)
    assert len(attempts) == 1
    assert attempts[0].status == "success"
    assert attempts[0].fetch_job_id == 1
    assert attempts[0].tracked_product_id == 1
    assert attempts[0].source_code == "testshop"
    assert attempts[0].strategy == "http_fetch"
    assert attempts[0].http_status == 200
    assert attempts[0].response_ms == 123
    assert attempts[0].product_data_found is True
    assert attempts[0].price_found is True
    assert attempts[0].image_found is True


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

    run_http_fetch_job(1, FakeFetcher(_successful_result()))

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

    run_http_fetch_job(1, FakeFetcher(_successful_result()))

    assert calls == [1]


def test_cashback_api_error_does_not_fail_successful_fetch_job(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    fetcher = FakeFetcher(_successful_result())

    def failing_resolver(*args, **kwargs):
        raise CashbackAPIUnavailableError("Cashback API is unavailable.")

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        failing_resolver,
        raising=False,
    )

    run_http_fetch_job(1, fetcher)

    job = db_session.get(FetchJob, 1)
    product = db_session.get(TrackedProduct, 1)
    assert job is not None
    assert product is not None
    db_session.refresh(job)
    db_session.refresh(product)
    assert fetcher.urls == ["https://testshop.local/product/1"]
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

    run_http_fetch_job(1, FakeFetcher(_successful_result()))

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

    run_http_fetch_job(1, FakeFetcher(_successful_result()))

    snapshot = db_session.scalar(select(TrackedProductCashback))
    assert snapshot is not None
    assert snapshot.cashback_status == "partner_estimated"
    assert snapshot.expected_cashback_min == Decimal("37.50")
    assert snapshot.expected_cashback_max == Decimal("90.00")
    assert snapshot.effective_price_conservative == Decimal("1462.40")
    assert snapshot.display_policy == "show_range_use_min_for_effective_price"


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


def test_price_not_found_does_not_call_cashback_resolver(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    calls = []

    def fake_resolver(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "resolve_and_store_product_cashback",
        fake_resolver,
        raising=False,
    )

    run_http_fetch_job(1, FakeFetcher(FetchError("price_not_found", "missing price")))

    job = db_session.get(FetchJob, 1)
    assert job is not None
    db_session.refresh(job)
    assert calls == []
    assert job.status == "failed"


def test_price_not_found_does_not_evaluate_price_alerts(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tracked_product(db_session)
    _fetch_job(db_session)
    calls = []

    def fake_evaluate_price_alerts(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    import app.services.fetch_job_runner as runner

    monkeypatch.setattr(
        runner,
        "evaluate_price_alerts",
        fake_evaluate_price_alerts,
        raising=False,
    )

    run_http_fetch_job(1, FakeFetcher(FetchError("price_not_found", "missing price")))

    job = db_session.get(FetchJob, 1)
    assert job is not None
    db_session.refresh(job)
    assert calls == []
    assert job.status == "failed"


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
