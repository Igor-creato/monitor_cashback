from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tests.conftest import signed_headers

from price_monitor.domains.reliability.models import FetchAttempt, FetchJob
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.service import WatchlistService


def test_product_detail_returns_card_contract(client: TestClient, session: Session) -> None:
    source = SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    product = result.item.product
    product.title = "Example Product"
    product.image_url = "https://example.com/image.jpg"
    product.rating_value = "4.7"
    product.current_price_minor = 12_345
    product.currency = "RUB"
    product.last_fetch_status = "ok"
    job = FetchJob(
        product_id=product.id,
        logical_key="watchlist:item-1:fetch:req-card",
        status="failed",
        status_reason="captcha_detected",
        scheduled_for=datetime(2026, 7, 2, 9, 0, tzinfo=UTC),
        started_at=datetime(2026, 7, 2, 9, 1, tzinfo=UTC),
        finished_at=datetime(2026, 7, 2, 9, 2, tzinfo=UTC),
    )
    session.add(job)
    session.flush()
    session.add(
        FetchAttempt(
            fetch_job_id=job.id,
            product_id=product.id,
            strategy="direct",
            status="failed",
            provider_name="citilink-http",
            provider_request_id="req-provider-1",
            provider_cost_minor=7,
            rendered=False,
            challenge_detected=True,
            block_reason=None,
            reason="captcha_detected",
            parser_version="citilink-v1",
            parser_confidence="0.90",
            created_at=datetime(2026, 7, 2, 9, 1, 30, tzinfo=UTC),
        )
    )
    session.commit()

    path = f"/api/v1/products/{product.id}"
    response = client.get(
        path,
        headers=signed_headers("GET", path, b"", request_id="req-card", idempotency_key=None),
    )

    assert response.status_code == 200
    assert response.json()["product"]["title"] == "Example Product"
    assert response.json()["source"]["logo_url"] == source.logo_url
    assert response.json()["actions"]["direct_url"] == product.canonical_url
    assert response.json()["latest_fetch"]["status"] == "failed"
    assert response.json()["latest_fetch"]["reason"] == "captcha_detected"
    assert response.json()["latest_fetch"]["strategy"] == "direct_http"
    assert response.json()["latest_fetch"]["parser_version"] == "citilink-v1"
    assert response.json()["latest_fetch"]["parser_confidence"] == "0.90"


def test_product_detail_resolves_supported_subdomain_to_monitored_source(
    client: TestClient, session: Session
) -> None:
    SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://shop.example.com/item?id=42",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-subdomain",
        max_tracked_products=10,
    )
    product = result.item.product
    product.title = "Subdomain Product"
    session.commit()

    path = f"/api/v1/products/{product.id}"
    response = client.get(
        path,
        headers=signed_headers(
            "GET", path, b"", request_id="req-card-subdomain", idempotency_key=None
        ),
    )

    assert response.status_code == 200
    assert response.json()["source"]["source_domain"] == "example.com"
    assert response.json()["product"]["title"] == "Subdomain Product"

def test_price_chart_returns_empty_state_without_currency_when_no_points(
    client: TestClient, session: Session
) -> None:
    SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:2",
        product_url="https://example.com/item?id=43",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-2",
        max_tracked_products=10,
    )
    product = result.item.product
    product.title = "Empty Chart Product"
    session.commit()

    chart_path = f"/api/v1/products/{product.id}/price-chart?days=7"
    response = client.get(
        chart_path,
        headers=signed_headers(
            "GET",
            chart_path,
            b"",
            request_id="req-empty-chart",
            idempotency_key=None,
        ),
    )

    assert response.status_code == 200
    assert response.json() == {
        "product_id": product.id,
        "currency": None,
        "points": [],
        "summary": {
            "lowest_price_minor": None,
            "latest_price_minor": None,
        },
    }
