from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.service import WatchlistService
from tests.conftest import signed_headers


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
