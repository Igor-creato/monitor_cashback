from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config
from app.main import app
from app.models.monitoring import (
    FetchJob,
    NotificationEvent,
    SourceConfig,
    SourceHealthEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

ADMIN_KEY = "admin-test-key"
SITE_ID = "savelloclub.ru"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> Iterator[TestClient]:
    if hasattr(config.settings, "admin_api_key"):
        monkeypatch.setattr(config.settings, "admin_api_key", SecretStr(ADMIN_KEY))
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _admin_headers(key: str = ADMIN_KEY) -> dict[str, str]:
    return {"ADMIN_API_KEY": key}


def _source(
    session: Session,
    *,
    source_code: str = "testshop",
    enabled: bool = True,
) -> SourceConfig:
    source = SourceConfig(
        source_code=source_code,
        source_name="Test Shop",
        enabled=enabled,
        fetch_strategy="http",
        min_fetch_interval_minutes=60,
        max_failures_before_quarantine=3,
        browser_fallback_enabled=False,
    )
    session.add(source)
    session.commit()
    return source


def _tracked_product(
    session: Session,
    *,
    product_id: int = 1,
    source: str = "testshop",
) -> TrackedProduct:
    product = TrackedProduct(
        id=product_id,
        source=source,
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://{source}.local/product/{product_id}",
        region_code="default",
        product_name=f"Product {product_id}",
        last_price=Decimal("1000.00"),
        last_old_price=Decimal("1200.00"),
        currency="RUB",
        last_availability=True,
    )
    session.add(product)
    session.commit()
    return product


def _subscription(
    session: Session,
    product: TrackedProduct,
    *,
    is_active: bool = True,
) -> UserProductSubscription:
    subscription = UserProductSubscription(
        site_id=SITE_ID,
        external_user_id=f"wp:{SITE_ID}:123",
        tracked_product=product,
        is_active=is_active,
    )
    session.add(subscription)
    session.commit()
    return subscription


def _cashback(
    session: Session,
    product: TrackedProduct,
    status: str,
) -> TrackedProductCashback:
    snapshot = TrackedProductCashback(
        tracked_product=product,
        cashback_status=status,
        merchant_id="merchant-1",
        merchant_name="Merchant",
        network="admitad",
        offer_id="offer-1",
        user_cashback_exact_rate=Decimal("3.5") if status == "partner_exact" else None,
        expected_cashback_exact=Decimal("35.00") if status == "partner_exact" else None,
        effective_price=Decimal("965.00") if status == "partner_exact" else None,
        confidence="exact" if status == "partner_exact" else "medium",
        display_policy="show_exact_rate"
        if status == "partner_exact"
        else "show_range_use_min_for_effective_price",
    )
    if status == "no_partner":
        snapshot.confidence = "none"
        snapshot.display_policy = "cashback_unavailable"
    session.add(snapshot)
    session.commit()
    return snapshot


def _fetch_job(
    session: Session,
    product: TrackedProduct,
    *,
    job_id: int,
    status: str,
    finished_at: datetime | None = None,
) -> FetchJob:
    job = FetchJob(
        id=job_id,
        tracked_product=product,
        status=status,
        reason="manual",
        priority=5,
        next_run_at=datetime(2026, 6, 8, 12, 0),
        finished_at=finished_at,
        error_text="fetch failed" if status == "failed" else None,
    )
    session.add(job)
    session.commit()
    return job


def test_admin_overview_requires_admin_api_key(client: TestClient) -> None:
    response = client.get("/admin/overview")

    assert response.status_code == 401


def test_admin_overview_counts_local_state(
    client: TestClient,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    _source(db_session, source_code="testshop", enabled=True)
    _source(db_session, source_code="disabledshop", enabled=False)
    no_partner_product = _tracked_product(db_session, product_id=1)
    estimated_product = _tracked_product(db_session, product_id=2)
    exact_product = _tracked_product(db_session, product_id=3)
    _subscription(db_session, no_partner_product, is_active=True)
    _subscription(db_session, estimated_product, is_active=False)
    active_subscription = _subscription(db_session, exact_product, is_active=True)
    _cashback(db_session, no_partner_product, "no_partner")
    _cashback(db_session, estimated_product, "partner_estimated")
    _cashback(db_session, exact_product, "partner_exact")
    _fetch_job(db_session, no_partner_product, job_id=1, status="queued")
    _fetch_job(
        db_session,
        estimated_product,
        job_id=2,
        status="failed",
        finished_at=now - timedelta(hours=2),
    )
    _fetch_job(
        db_session,
        exact_product,
        job_id=3,
        status="failed",
        finished_at=now - timedelta(days=2),
    )
    db_session.add(
        NotificationEvent(
            site_id=SITE_ID,
            external_user_id=f"wp:{SITE_ID}:123",
            subscription=active_subscription,
            tracked_product=exact_product,
            event_type="target_price_reached",
            status="pending",
            payload_json="{}",
        )
    )
    db_session.commit()

    response = client.get("/admin/overview", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json() == {
        "products_total": 3,
        "active_subscriptions_total": 2,
        "fetch_jobs_queued": 1,
        "fetch_jobs_failed_24h": 1,
        "cashback_no_partner_total": 1,
        "cashback_estimated_total": 1,
        "cashback_exact_total": 1,
        "notification_events_pending": 1,
        "sources_enabled": 1,
    }


def test_admin_sources_list_returns_source_configs(
    client: TestClient,
    db_session: Session,
) -> None:
    _source(db_session, source_code="z-shop", enabled=False)
    _source(db_session, source_code="a-shop", enabled=True)

    response = client.get("/admin/sources", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "source_code": "a-shop",
            "source_name": "Test Shop",
            "enabled": True,
            "fetch_strategy": "http",
            "min_fetch_interval_minutes": 60,
            "max_failures_before_quarantine": 3,
            "browser_fallback_enabled": False,
        },
        {
            "source_code": "z-shop",
            "source_name": "Test Shop",
            "enabled": False,
            "fetch_strategy": "http",
            "min_fetch_interval_minutes": 60,
            "max_failures_before_quarantine": 3,
            "browser_fallback_enabled": False,
        },
    ]


def test_admin_patch_source_changes_only_allowed_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    source = _source(db_session)

    response = client.patch(
        "/admin/sources/testshop",
        headers=_admin_headers(),
        json={
            "enabled": False,
            "min_fetch_interval_minutes": 120,
            "max_failures_before_quarantine": 5,
            "browser_fallback_enabled": True,
            "source_name": "Changed Name",
            "fetch_strategy": "browser",
            "source_code": "other",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_code": "testshop",
        "source_name": "Test Shop",
        "enabled": False,
        "fetch_strategy": "http",
        "min_fetch_interval_minutes": 120,
        "max_failures_before_quarantine": 5,
        "browser_fallback_enabled": True,
    }
    db_session.refresh(source)
    assert source.source_name == "Test Shop"
    assert source.fetch_strategy == "http"
    assert source.source_code == "testshop"


def test_admin_products_list_returns_cashback_status(
    client: TestClient,
    db_session: Session,
) -> None:
    product_with_cashback = _tracked_product(db_session, product_id=1)
    _tracked_product(db_session, product_id=2)
    _cashback(db_session, product_with_cashback, "partner_exact")

    response = client.get("/admin/products", headers=_admin_headers())

    assert response.status_code == 200
    assert [item["cashback_status"] for item in response.json()["items"]] == [
        "partner_exact",
        "unknown",
    ]
    assert response.json()["items"][0]["tracked_product_id"] == 1
    assert response.json()["items"][0]["last_price"] == "1000.00"


def test_admin_product_detail_returns_local_cashback_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session, product_id=1)
    _cashback(db_session, product, "partner_exact")

    response = client.get("/admin/products/1", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json()["tracked_product_id"] == 1
    assert response.json()["cashback_status"] == "partner_exact"
    assert response.json()["cashback"]["merchant_id"] == "merchant-1"
    assert response.json()["cashback"]["expected_cashback_exact"] == "35.00"


def test_admin_jobs_list_returns_fetch_jobs(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session)
    _fetch_job(db_session, product, job_id=1, status="queued")
    _fetch_job(db_session, product, job_id=2, status="failed")

    response = client.get("/admin/jobs", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "job_id": 2,
            "tracked_product_id": 1,
            "source": "testshop",
            "status": "failed",
            "priority": 5,
            "attempt": 0,
            "reason": "manual",
            "next_run_at": "2026-06-08T12:00:00",
            "started_at": None,
            "finished_at": None,
            "error_text": "fetch failed",
        },
        {
            "job_id": 1,
            "tracked_product_id": 1,
            "source": "testshop",
            "status": "queued",
            "priority": 5,
            "attempt": 0,
            "reason": "manual",
            "next_run_at": "2026-06-08T12:00:00",
            "started_at": None,
            "finished_at": None,
            "error_text": None,
        },
    ]


def test_admin_errors_returns_local_error_records(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session)
    subscription = _subscription(db_session, product)
    _fetch_job(db_session, product, job_id=1, status="failed")
    db_session.add_all(
        [
            NotificationEvent(
                site_id=SITE_ID,
                external_user_id=f"wp:{SITE_ID}:123",
                subscription=subscription,
                tracked_product=product,
                event_type="target_price_reached",
                status="failed",
                payload_json="{}",
                error_text="notify failed",
            ),
            SourceHealthEvent(
                source_code="testshop",
                event_type="http_429",
                status_code=429,
                response_ms=250,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/admin/errors", headers=_admin_headers())

    assert response.status_code == 200
    assert [item["error_type"] for item in response.json()["items"]] == [
        "fetch_job_failed",
        "notification_event_failed",
        "source_health_http_429",
    ]
