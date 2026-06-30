import json
from hashlib import sha256

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import signed_headers

from price_monitor.domains.reliability.models import IdempotencyRecord, OutboxEvent
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.domains.watchlist.service import WatchlistService


def test_openapi_exposes_initial_wordpress_facing_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])

    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/watchlist/items" in paths
    assert "/api/v1/watchlist/items/{item_id}" in paths
    assert "/api/v1/products/{product_id}" in paths
    assert "/api/v1/products/{product_id}/price-history" in paths
    assert "/api/v1/products/{product_id}/price-chart" in paths
    assert "/api/v1/sources/status" in paths


def test_watchlist_create_requires_hmac_and_idempotency_key(client: TestClient) -> None:
    response = client.post("/api/v1/watchlist/items", json={"url": "https://example.com/item"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_watchlist_list_requires_hmac(client: TestClient) -> None:
    response = client.get("/api/v1/watchlist/items")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_product_detail_requires_hmac(client: TestClient) -> None:
    response = client.get("/api/v1/products/product-1")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_watchlist_create_returns_stable_contract_and_deduplicates(
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
    path = "/api/v1/watchlist/items"
    body = {
        "user_id": "wp-user-1",
        "url": "https://example.com/item?id=42&utm_source=ad",
        "target_price_minor": 12_345,
        "currency": "RUB",
    }
    raw_body = json.dumps(body, separators=(",", ":")).encode()

    first = client.post(
        path,
        content=raw_body,
        headers=signed_headers(
            "POST", path, raw_body, request_id="req-1", idempotency_key="idem-1"
        ),
    )
    second = client.post(
        path,
        content=raw_body,
        headers=signed_headers(
            "POST", path, raw_body, request_id="req-2", idempotency_key="idem-2"
        ),
    )

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert first.json()["item"]["canonical_url"] == "https://example.com/item?id=42"
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_watchlist_item"


def test_watchlist_create_rejects_negative_target_price_with_stable_error(
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
    path = "/api/v1/watchlist/items"
    body = {
        "user_id": "wp-user-1",
        "url": "https://example.com/item?id=13",
        "target_price_minor": -1,
        "currency": "RUB",
    }
    raw_body = json.dumps(body, separators=(",", ":")).encode()

    response = client.post(
        path,
        content=raw_body,
        headers=signed_headers(
            "POST", path, raw_body, request_id="req-negative-price", idempotency_key="idem-neg"
        ),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_target_price",
            "message": "Некорректная целевая цена",
        }
    }


def test_idempotency_key_replay_returns_original_response(
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
    path = "/api/v1/watchlist/items"
    body = {
        "user_id": "wp-user-1",
        "url": "https://example.com/replay",
        "target_price_minor": None,
        "currency": "RUB",
    }
    raw_body = json.dumps(body, separators=(",", ":")).encode()
    headers = signed_headers(
        "POST", path, raw_body, request_id="req-1", idempotency_key="idem-replay"
    )

    first = client.post(path, content=raw_body, headers=headers)
    second = client.post(path, content=raw_body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()


def test_watchlist_delete_replays_completed_idempotent_response(
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
    created = WatchlistService(session).add_item(
        user_id="wp-user-1",
        product_url="https://example.com/delete-me",
        target_price_minor=None,
        currency="RUB",
        request_id="req-create-delete",
    )
    item_id = created.item.id
    path = f"/api/v1/watchlist/items/{item_id}"
    headers = signed_headers(
        "DELETE", path, b"", request_id="req-delete-1", idempotency_key="idem-delete-1"
    )

    first = client.delete(path, headers=headers)
    second = client.delete(path, headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204
    deleted_item = session.get(WatchlistItem, item_id)
    assert deleted_item is not None
    assert deleted_item.status == "deleted"

    events = session.scalars(
        select(OutboxEvent).where(OutboxEvent.event_type == "watchlist.item_deleted")
    ).all()
    assert len(events) == 1

    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.key == "idem-delete-1",
            IdempotencyRecord.route == "DELETE /api/v1/watchlist/items",
        )
    )
    assert record is not None
    assert record.status == "completed"
    assert record.response_status == 204
    assert record.response_body == {}


def test_watchlist_delete_rejects_same_idempotency_key_for_different_target(
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
    first_item = WatchlistService(session).add_item(
        user_id="wp-user-1",
        product_url="https://example.com/delete-a",
        target_price_minor=None,
        currency="RUB",
        request_id="req-create-a",
    ).item
    second_item = WatchlistService(session).add_item(
        user_id="wp-user-1",
        product_url="https://example.com/delete-b",
        target_price_minor=None,
        currency="RUB",
        request_id="req-create-b",
    ).item
    first_path = f"/api/v1/watchlist/items/{first_item.id}"
    second_path = f"/api/v1/watchlist/items/{second_item.id}"

    first = client.delete(
        first_path,
        headers=signed_headers(
            "DELETE",
            first_path,
            b"",
            request_id="req-delete-a",
            idempotency_key="idem-delete-conflict",
        ),
    )
    second = client.delete(
        second_path,
        headers=signed_headers(
            "DELETE",
            second_path,
            b"",
            request_id="req-delete-b",
            idempotency_key="idem-delete-conflict",
        ),
    )

    assert first.status_code == 204
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_conflict"
    still_active = session.get(WatchlistItem, second_item.id)
    assert still_active is not None
    assert still_active.status == "active"


def test_watchlist_create_rejects_pending_same_key_retry(
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
    path = "/api/v1/watchlist/items"
    body = {
        "user_id": "wp-user-1",
        "url": "https://example.com/pending-create",
        "target_price_minor": None,
        "currency": "RUB",
    }
    raw_body = json.dumps(body, separators=(",", ":")).encode()
    session.add(
        IdempotencyRecord(
            key="idem-pending-create",
            route="POST /api/v1/watchlist/items",
            request_hash=sha256(raw_body).hexdigest(),
            status="pending",
        )
    )
    session.commit()

    response = client.post(
        path,
        content=raw_body,
        headers=signed_headers(
            "POST",
            path,
            raw_body,
            request_id="req-pending-create",
            idempotency_key="idem-pending-create",
        ),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert "progress" in response.json()["error"]["message"]
    items = session.scalars(select(WatchlistItem)).all()
    assert items == []


def test_watchlist_delete_rejects_pending_same_key_retry(
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
    created = WatchlistService(session).add_item(
        user_id="wp-user-1",
        product_url="https://example.com/pending-delete",
        target_price_minor=None,
        currency="RUB",
        request_id="req-create-pending-delete",
    )
    item_id = created.item.id
    path = f"/api/v1/watchlist/items/{item_id}"
    session.add(
        IdempotencyRecord(
            key="idem-pending-delete",
            route="DELETE /api/v1/watchlist/items",
            request_hash=sha256(f"{item_id}:{sha256(b'').hexdigest()}".encode()).hexdigest(),
            status="pending",
        )
    )
    session.commit()

    response = client.delete(
        path,
        headers=signed_headers(
            "DELETE",
            path,
            b"",
            request_id="req-pending-delete",
            idempotency_key="idem-pending-delete",
        ),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert "progress" in response.json()["error"]["message"]
    item = session.get(WatchlistItem, item_id)
    assert item is not None
    assert item.status == "active"
    events = session.scalars(
        select(OutboxEvent).where(OutboxEvent.event_type == "watchlist.item_deleted")
    ).all()
    assert events == []


def test_health_and_read_endpoints_return_stable_empty_foundation_contract(
    client: TestClient,
    session: Session,
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
    created = WatchlistService(session).add_item(
        user_id="wp-empty-reader",
        product_url="https://example.com/empty-chart",
        target_price_minor=None,
        currency="RUB",
        request_id="req-empty-chart",
    )
    assert created.item is not None
    assert created.item.product is not None

    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["status"] == "ok"
    assert client.get("/api/v1/sources/status").json() == {"sources": []}

    history_path = "/api/v1/products/missing-product/price-history"
    history = client.get(
        history_path,
        headers=signed_headers(
            "GET",
            history_path,
            b"",
            request_id="req-empty-history",
            idempotency_key=None,
        ),
    ).json()
    assert history == {"product_id": "missing-product", "points": []}

    chart_path = f"/api/v1/products/{created.item.product.id}/price-chart?days=30"
    chart = client.get(
        chart_path,
        headers=signed_headers(
            "GET",
            chart_path,
            b"",
            request_id="req-empty-chart",
            idempotency_key=None,
        ),
    )
    assert chart.status_code == 200
    assert chart.json() == {
        "product_id": created.item.product.id,
        "currency": None,
        "points": [],
        "summary": {"lowest_price_minor": None, "latest_price_minor": None},
    }
