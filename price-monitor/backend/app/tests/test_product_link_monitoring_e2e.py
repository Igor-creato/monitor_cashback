from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import FetchJob, PriceHistory, TrackedProduct
from app.product_monitoring.ozon import parse_ozon_public_page
from app.schemas.watchlist import WatchlistItemCreate
from app.services.fetch_job_runner import run_http_fetch_job
from app.services.fetch_jobs import enqueue_fetch_job
from app.services.multistage_fetch_executor import execute_product_fetch
from app.services.price_chart import build_price_chart
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserPriceMonitorLimits,
)
from app.services.watchlist import add_watchlist_item

SITE_ID = "savelloclub.ru"
EXTERNAL_USER_ID = "wp:savelloclub.ru:123"
FETCHED_AT = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


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
    import app.services.price_chart as price_chart

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
    monkeypatch.setattr(
        price_chart,
        "current_utc_datetime",
        lambda: datetime(2026, 6, 27, 12, 0),
    )

    with Session(engine) as session:
        yield session


def test_ozon_watchlist_fetch_writes_price_history_and_chart(
    db_session: Session,
) -> None:
    result = add_watchlist_item(
        db_session,
        WatchlistItemCreate(
            site_id=SITE_ID,
            external_user_id=EXTERNAL_USER_ID,
            product_url=(
                "https://www.ozon.ru/product/smartfon-test-123456789/"
                "?utm_source=ad&region=msk"
            ),
            target_price=Decimal("25000.00"),
            region_code="default",
        ),
        limits_provider=lambda site_id, external_user_id: _limits(external_user_id),
    )
    enqueue_status = enqueue_fetch_job(
        db_session,
        result.subscription.tracked_product_id,
        "manual_watchlist_add",
        now=FETCHED_AT,
    )
    job = db_session.scalar(select(FetchJob))

    assert enqueue_status == "created"
    assert job is not None

    def ozon_executor(tracked_product_id, context):
        context.ozon_public_fetcher = lambda tracked_product, timeout: (
            parse_ozon_public_page(_ozon_fixture_html(), fetched_at=FETCHED_AT)
        )
        return execute_product_fetch(tracked_product_id, context)

    run_http_fetch_job(job.id, object(), product_fetch_executor=ozon_executor)

    product = db_session.scalar(select(TrackedProduct))
    history = db_session.scalar(select(PriceHistory))
    assert product is not None
    assert product.source == "ozon"
    assert product.external_product_id == "123456789"
    assert product.product_name == "Ozon E2E Phone"
    assert product.last_price == Decimal("24999.90")
    assert product.last_status == "ok"
    assert history is not None
    assert history.price_current == Decimal("24999.90")

    chart = build_price_chart(
        db_session,
        tracked_product_id=product.id,
        site_id=SITE_ID,
        external_user_id=EXTERNAL_USER_ID,
    )

    assert chart is not None
    assert chart.summary.current_price == "24999.90"
    assert chart.series[0].price == "24999.90"


def _limits(external_user_id: str) -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id=external_user_id,
        tariff="basic",
        limits=PriceMonitorLimitValues(
            max_tracked_products=100,
            history_days=30,
            min_fetch_interval_minutes=360,
            alerts_per_day=10,
            manual_refresh_per_day=3,
            browser_fallback_allowed=False,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0.7"),
            cashback_currency="RUB",
        ),
    )


def _ozon_fixture_html() -> str:
    return """
    <html>
      <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Ozon E2E Phone",
          "image": "https://cdn.ozon.example/e2e-phone.jpg",
          "offers": {
            "@type": "Offer",
            "price": "24999.90",
            "priceCurrency": "RUB",
            "availability": "https://schema.org/InStock",
            "seller": {"name": "Ozon"}
          }
        }
      </script>
    </html>
    """
