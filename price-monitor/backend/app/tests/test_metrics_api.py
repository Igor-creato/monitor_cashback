from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.main import app
from app.models.monitoring import (
    FetchJob,
    NotificationEvent,
    SourceHealthEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

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
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _tracked_product(
    session: Session,
    *,
    product_id: int,
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
        currency="RUB",
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
    *,
    status: str,
) -> TrackedProductCashback:
    snapshot = TrackedProductCashback(
        tracked_product=product,
        cashback_status=status,
        confidence="exact" if status == "partner_exact" else "none",
        display_policy="show_exact_rate"
        if status == "partner_exact"
        else "cashback_unavailable",
    )
    session.add(snapshot)
    session.commit()
    return snapshot


def _fetch_job(
    session: Session,
    product: TrackedProduct,
    *,
    job_id: int,
    status: str,
) -> FetchJob:
    job = FetchJob(
        id=job_id,
        tracked_product=product,
        status=status,
        reason="manual",
        next_run_at=datetime(2026, 6, 8, 12, 0),
    )
    session.add(job)
    session.commit()
    return job


def _notification_event(
    session: Session,
    subscription: UserProductSubscription,
    product: TrackedProduct,
    *,
    status: str,
    event_type: str,
) -> NotificationEvent:
    event = NotificationEvent(
        site_id=SITE_ID,
        external_user_id=f"wp:{SITE_ID}:123",
        subscription=subscription,
        tracked_product=product,
        event_type=event_type,
        status=status,
        payload_json="{}",
    )
    session.add(event)
    session.commit()
    return event


def test_metrics_endpoint_returns_prometheus_text(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session, product_id=1)
    subscription = _subscription(db_session, product)
    _cashback(db_session, product, status="partner_exact")
    _fetch_job(db_session, product, job_id=1, status="queued")
    _notification_event(
        db_session,
        subscription,
        product,
        status="pending",
        event_type="target_price_reached",
    )
    db_session.add(
        SourceHealthEvent(source_code="testshop", event_type="success")
    )
    db_session.commit()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "text/plain; version=0.0.4; charset=utf-8"
    )
    body = response.text
    assert "price_monitor_products_total " in body
    assert "price_monitor_active_subscriptions_total " in body
    assert "price_monitor_fetch_jobs_total" in body
    assert "price_monitor_cashback_status_total" in body
    assert "price_monitor_notification_events_total" in body
    assert "price_monitor_source_events_total" in body


def test_cashback_status_metrics_reflect_local_snapshots(
    client: TestClient,
    db_session: Session,
) -> None:
    exact_product = _tracked_product(db_session, product_id=1)
    no_partner_product = _tracked_product(db_session, product_id=2)
    _cashback(db_session, exact_product, status="partner_exact")
    _cashback(db_session, no_partner_product, status="no_partner")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        'price_monitor_cashback_status_total{cashback_status="partner_exact"} 1'
        in response.text
    )
    assert (
        'price_monitor_cashback_status_total{cashback_status="no_partner"} 1'
        in response.text
    )


def test_notification_metrics_reflect_local_events(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session, product_id=1)
    subscription = _subscription(db_session, product)
    _notification_event(
        db_session,
        subscription,
        product,
        status="pending",
        event_type="target_price_reached",
    )
    _notification_event(
        db_session,
        subscription,
        product,
        status="pending",
        event_type="target_price_reached",
    )
    _notification_event(
        db_session,
        subscription,
        product,
        status="failed",
        event_type="target_effective_price_reached",
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        'price_monitor_notification_events_total{status="pending",'
        'event_type="target_price_reached"} 2'
    ) in response.text
    assert (
        'price_monitor_notification_events_total{status="failed",'
        'event_type="target_effective_price_reached"} 1'
    ) in response.text
