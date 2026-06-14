from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import (
    FetchAttempt,
    FetchJob,
    NotificationEvent,
    PriceHistory,
    ProxyEndpoint,
    ProxyPool,
    SourceHealthEvent,
    SourceQuarantineState,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

SECRET = "incoming-test-secret"
SITE_ID = "savelloclub.ru"
USER_ID = f"wp:{SITE_ID}:123"
NOW = 1_800_000_000


def _signature(timestamp: str, raw_body: bytes, secret: str = SECRET) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()


def _headers(raw_body: bytes = b"", *, site_id: str = SITE_ID) -> dict[str, str]:
    timestamp = str(NOW)
    return {
        "X-Savello-Site": site_id,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": _signature(timestamp, raw_body),
    }


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
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(SECRET),
    )
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: NOW)

    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _tracked_product(
    session: Session,
    *,
    product_id: int,
    source: str = "testshop",
    image_url: str | None = None,
    image_object_key: str | None = None,
) -> TrackedProduct:
    product = TrackedProduct(
        id=product_id,
        source=source,
        external_product_id=f"sku-{product_id}",
        canonical_url=f"https://{source}.local/product/{product_id}",
        region_code="default",
        product_name=f"Product {product_id}",
        image_url=image_url,
        image_object_key=image_object_key,
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


def _price_history(
    session: Session,
    product: TrackedProduct,
) -> PriceHistory:
    point = PriceHistory(
        tracked_product=product,
        price_current=Decimal("1000.00"),
        currency="RUB",
        availability=True,
        fetched_at=datetime(2026, 6, 8, 12, 0),
    )
    session.add(point)
    session.commit()
    return point


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


def _proxy_pool(
    session: Session,
    *,
    pool_id: int,
    tier: str,
    source: str = "testshop",
    enabled: bool = True,
) -> ProxyPool:
    pool = ProxyPool(
        id=pool_id,
        source=source,
        purpose="price_fetch",
        tier=tier,
        enabled=enabled,
        cost_per_request=Decimal("0.01000000"),
    )
    session.add(pool)
    session.commit()
    return pool


def _proxy_endpoint(
    session: Session,
    pool: ProxyPool,
    *,
    endpoint_id: int,
) -> ProxyEndpoint:
    endpoint = ProxyEndpoint(
        id=endpoint_id,
        pool=pool,
        endpoint_ref="http://user:secret-password@proxy.local:8080",
        enabled=True,
        max_concurrency=5,
        current_concurrency=1,
    )
    session.add(endpoint)
    session.commit()
    return endpoint


def _fetch_attempt(
    session: Session,
    product: TrackedProduct,
    *,
    attempt_id: int,
    source_code: str = "testshop",
    strategy: str = "direct_http",
    status: str = "success",
    error_type: str | None = None,
    cost_estimated: Decimal | None = Decimal("0.100000"),
    proxy_pool_id: int | None = None,
    proxy_endpoint_id: int | None = None,
) -> FetchAttempt:
    attempt = FetchAttempt(
        id=attempt_id,
        tracked_product_id=product.id,
        source_code=source_code,
        strategy=strategy,
        status=status,
        error_type=error_type,
        cost_estimated=cost_estimated,
        proxy_pool_id=proxy_pool_id,
        proxy_endpoint_id=proxy_endpoint_id,
        product_data_found=status == "success",
        price_found=status == "success",
        image_found=status == "success",
    )
    session.add(attempt)
    session.commit()
    return attempt


def _quarantine_state(
    session: Session,
    *,
    source_code: str,
    status: str,
) -> SourceQuarantineState:
    state = SourceQuarantineState(source_code=source_code, status=status)
    session.add(state)
    session.commit()
    return state


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
    _fetch_attempt(db_session, product, attempt_id=1)
    _fetch_attempt(db_session, product, attempt_id=2, strategy="playwright")
    _fetch_attempt(
        db_session,
        product,
        attempt_id=3,
        status="failed",
        error_type="parser_error",
    )
    _proxy_pool(db_session, pool_id=1, tier="cheap")
    _quarantine_state(db_session, source_code="testshop", status="active")
    db_session.add(SourceHealthEvent(source_code="testshop", event_type="success"))
    db_session.commit()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    )
    body = response.text
    assert "price_monitor_products_total " in body
    assert "price_monitor_active_subscriptions_total " in body
    assert "price_monitor_fetch_jobs_total" in body
    assert "price_monitor_cashback_status_total" in body
    assert "price_monitor_notification_events_total" in body
    assert "price_monitor_source_events_total" in body
    assert "price_monitor_fetch_attempts_total" in body
    assert "price_monitor_fetch_cost_estimated_total" in body
    assert "price_monitor_proxy_pool_active_total" in body
    assert "price_monitor_source_quarantine_total" in body
    assert "price_monitor_browser_fallback_total" in body
    assert "price_monitor_image_copy_total" in body
    assert "price_monitor_extraction_errors_total" in body
    assert "price_monitor_chart_requests_total" in body


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


def test_fetch_attempt_metrics_reflect_status_and_error_type(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session, product_id=1)
    _fetch_attempt(
        db_session,
        product,
        attempt_id=1,
        strategy="direct_http",
        status="success",
        error_type=None,
    )
    _fetch_attempt(
        db_session,
        product,
        attempt_id=2,
        strategy="direct_http",
        status="failed",
        error_type="http_403",
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        'price_monitor_fetch_attempts_total{source="testshop",'
        'strategy="direct_http",status="success",error_type="none"} 1'
    ) in response.text
    assert (
        'price_monitor_fetch_attempts_total{source="testshop",'
        'strategy="direct_http",status="failed",error_type="http_403"} 1'
    ) in response.text


def test_proxy_tier_metrics_reflect_cost_and_pool_status(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session, product_id=1)
    cheap_pool = _proxy_pool(db_session, pool_id=1, tier="cheap", enabled=True)
    disabled_pool = _proxy_pool(
        db_session,
        pool_id=2,
        tier="residential",
        source="othershop",
        enabled=False,
    )
    endpoint = _proxy_endpoint(db_session, cheap_pool, endpoint_id=1)
    _fetch_attempt(
        db_session,
        product,
        attempt_id=1,
        strategy="cheap_proxy_http",
        cost_estimated=Decimal("0.250000"),
        proxy_pool_id=cheap_pool.id,
        proxy_endpoint_id=endpoint.id,
    )
    _fetch_attempt(
        db_session,
        product,
        attempt_id=2,
        strategy="direct_http",
        cost_estimated=Decimal("0.050000"),
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        'price_monitor_fetch_cost_estimated_total{source="testshop",'
        'strategy="cheap_proxy_http",proxy_tier="cheap"} 0.250000'
    ) in response.text
    assert (
        'price_monitor_fetch_cost_estimated_total{source="testshop",'
        'strategy="direct_http",proxy_tier="none"} 0.050000'
    ) in response.text
    assert (
        'price_monitor_proxy_pool_active_total{tier="cheap",status="enabled"} 1'
        in response.text
    )
    assert (
        'price_monitor_proxy_pool_active_total{tier="residential",status="disabled"} 1'
        in response.text
    )
    assert "secret-password" not in response.text
    assert "endpoint_ref" not in response.text
    assert disabled_pool.id == 2


def test_quarantine_image_browser_and_extraction_metrics_reflect_local_state(
    client: TestClient,
    db_session: Session,
) -> None:
    copied = _tracked_product(
        db_session,
        product_id=1,
        image_url="https://cdn.local/products/1.webp",
        image_object_key="products/1/copied.webp",
    )
    external = _tracked_product(
        db_session,
        product_id=2,
        image_url="https://shop.local/image.jpg",
    )
    _tracked_product(db_session, product_id=3)
    _fetch_attempt(
        db_session,
        copied,
        attempt_id=1,
        strategy="playwright",
        source_code="testshop",
    )
    _fetch_attempt(
        db_session,
        copied,
        attempt_id=2,
        strategy="camoufox",
        source_code="testshop",
    )
    _fetch_attempt(
        db_session,
        copied,
        attempt_id=3,
        strategy="direct_http",
        status="failed",
        error_type="parser_error",
    )
    _fetch_attempt(
        db_session,
        external,
        attempt_id=4,
        strategy="direct_http",
        status="failed",
        error_type="price_not_found",
    )
    for status in ("active", "cooldown", "quarantined", "disabled"):
        _quarantine_state(
            db_session,
            source_code=f"{status}shop",
            status=status,
        )

    response = client.get("/metrics")

    assert response.status_code == 200
    for status in ("active", "cooldown", "quarantined", "disabled"):
        assert (
            f'price_monitor_source_quarantine_total{{status="{status}"}} 1'
            in response.text
        )
    assert 'price_monitor_image_copy_total{status="copied"} 1' in response.text
    assert 'price_monitor_image_copy_total{status="external_url"} 1' in response.text
    assert 'price_monitor_image_copy_total{status="missing"} 1' in response.text
    assert (
        'price_monitor_browser_fallback_total{source="testshop",'
        'browser_engine="playwright"} 1'
    ) in response.text
    assert (
        'price_monitor_browser_fallback_total{source="testshop",'
        'browser_engine="camoufox"} 1'
    ) in response.text
    assert (
        'price_monitor_extraction_errors_total{source="testshop",'
        'error_type="parser_error"} 1'
    ) in response.text
    assert (
        'price_monitor_extraction_errors_total{source="testshop",'
        'error_type="price_not_found"} 1'
    ) in response.text


def test_chart_requests_counter_increments_for_valid_signed_chart_requests(
    client: TestClient,
    db_session: Session,
) -> None:
    product = _tracked_product(db_session, product_id=1)
    _subscription(db_session, product)
    _price_history(db_session, product)

    chart_response = client.get(
        f"/v1/products/{product.id}/price-chart"
        f"?site_id={SITE_ID}&external_user_id={USER_ID}",
        headers=_headers(),
    )
    metrics_response = client.get("/metrics")

    assert chart_response.status_code == 200
    assert metrics_response.status_code == 200
    assert "price_monitor_chart_requests_total 1" in metrics_response.text


def test_chart_requests_counter_increments_for_valid_signed_chart_404(
    client: TestClient,
    db_session: Session,
) -> None:
    chart_response = client.get(
        f"/v1/products/999/price-chart?site_id={SITE_ID}&external_user_id={USER_ID}",
        headers=_headers(),
    )
    metrics_response = client.get("/metrics")

    assert chart_response.status_code == 404
    assert metrics_response.status_code == 200
    assert "price_monitor_chart_requests_total 1" in metrics_response.text
