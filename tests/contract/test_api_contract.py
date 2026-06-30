import importlib
import json
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import signed_headers

from price_monitor.domains.reliability.models import FetchJob, IdempotencyRecord, OutboxEvent
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
    assert "/api/v1/watchlist/items/{item_id}/refresh" in paths
    assert "/api/v1/products/{product_id}" in paths
    assert "/api/v1/products/{product_id}/price-history" in paths
    assert "/api/v1/products/{product_id}/price-chart" in paths
    assert "/api/v1/sources/status" in paths

    watchlist_item_methods = set(schema["paths"]["/api/v1/watchlist/items/{item_id}"])
    assert {"delete", "patch"} <= watchlist_item_methods
    assert "post" in schema["paths"]["/api/v1/watchlist/items/{item_id}/refresh"]


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
    raw_body = json.dumps({"user_id": "wp-user-1"}, separators=(",", ":")).encode()
    headers = signed_headers(
        "DELETE",
        path,
        raw_body,
        request_id="req-delete-1",
        idempotency_key="idem-delete-1",
    )

    first = client.request("DELETE", path, content=raw_body, headers=headers)
    second = client.request("DELETE", path, content=raw_body, headers=headers)

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
    first_item = (
        WatchlistService(session)
        .add_item(
            user_id="wp-user-1",
            product_url="https://example.com/delete-a",
            target_price_minor=None,
            currency="RUB",
            request_id="req-create-a",
        )
        .item
    )
    second_item = (
        WatchlistService(session)
        .add_item(
            user_id="wp-user-1",
            product_url="https://example.com/delete-b",
            target_price_minor=None,
            currency="RUB",
            request_id="req-create-b",
        )
        .item
    )
    first_path = f"/api/v1/watchlist/items/{first_item.id}"
    second_path = f"/api/v1/watchlist/items/{second_item.id}"

    first_body = json.dumps({"user_id": "wp-user-1"}, separators=(",", ":")).encode()
    second_body = json.dumps({"user_id": "wp-user-1"}, separators=(",", ":")).encode()
    first = client.request(
        "DELETE",
        first_path,
        content=first_body,
        headers=signed_headers(
            "DELETE",
            first_path,
            first_body,
            request_id="req-delete-a",
            idempotency_key="idem-delete-conflict",
        ),
    )
    second = client.request(
        "DELETE",
        second_path,
        content=second_body,
        headers=signed_headers(
            "DELETE",
            second_path,
            second_body,
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
    raw_body = json.dumps({"user_id": "wp-user-1"}, separators=(",", ":")).encode()
    session.add(
        IdempotencyRecord(
            key="idem-pending-delete",
            route="DELETE /api/v1/watchlist/items",
            request_hash=sha256(f"{item_id}:{sha256(raw_body).hexdigest()}".encode()).hexdigest(),
            status="pending",
        )
    )
    session.commit()

    response = client.request(
        "DELETE",
        path,
        content=raw_body,
        headers=signed_headers(
            "DELETE",
            path,
            raw_body,
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


def test_watchlist_patch_updates_target_price_and_wrong_owner_is_not_found(
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
        product_url="https://example.com/patch-me",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-create-patch",
    )
    item_id = created.item.id
    path = f"/api/v1/watchlist/items/{item_id}"
    wrong_body = json.dumps(
        {"user_id": "wp-user-2", "target_price_minor": 7777}, separators=(",", ":")
    ).encode()
    wrong_owner = client.request(
        "PATCH",
        path,
        content=wrong_body,
        headers=signed_headers(
            "PATCH",
            path,
            wrong_body,
            request_id="req-patch-wrong-owner",
            idempotency_key="idem-patch-wrong-owner",
        ),
    )

    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["error"]["code"] == "watchlist_item_not_found"
    unchanged = session.get(WatchlistItem, item_id)
    assert unchanged is not None
    assert unchanged.target_price_minor == 10_000

    correct_body = json.dumps(
        {"user_id": "wp-user-1", "target_price_minor": 7777}, separators=(",", ":")
    ).encode()
    updated = client.request(
        "PATCH",
        path,
        content=correct_body,
        headers=signed_headers(
            "PATCH",
            path,
            correct_body,
            request_id="req-patch-correct-owner",
            idempotency_key="idem-patch-correct-owner",
        ),
    )

    assert updated.status_code == 200
    assert updated.json()["item"]["target_price_minor"] == 7777
    refreshed = session.get(WatchlistItem, item_id)
    assert refreshed is not None
    assert refreshed.target_price_minor == 7777


def test_watchlist_delete_requires_matching_owner_and_replays_for_owner(
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
        product_url="https://example.com/delete-owner-scope",
        target_price_minor=None,
        currency="RUB",
        request_id="req-create-owner-delete",
    )
    item_id = created.item.id
    path = f"/api/v1/watchlist/items/{item_id}"
    wrong_body = json.dumps({"user_id": "wp-user-2"}, separators=(",", ":")).encode()
    wrong_owner = client.request(
        "DELETE",
        path,
        content=wrong_body,
        headers=signed_headers(
            "DELETE",
            path,
            wrong_body,
            request_id="req-delete-wrong-owner",
            idempotency_key="idem-delete-wrong-owner",
        ),
    )

    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["error"]["code"] == "watchlist_item_not_found"
    still_active = session.get(WatchlistItem, item_id)
    assert still_active is not None
    assert still_active.status == "active"

    correct_body = json.dumps({"user_id": "wp-user-1"}, separators=(",", ":")).encode()
    headers = signed_headers(
        "DELETE",
        path,
        correct_body,
        request_id="req-delete-correct-owner",
        idempotency_key="idem-delete-correct-owner",
    )
    first = client.request("DELETE", path, content=correct_body, headers=headers)
    second = client.request("DELETE", path, content=correct_body, headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204
    deleted = session.get(WatchlistItem, item_id)
    assert deleted is not None
    assert deleted.status == "deleted"


def test_watchlist_refresh_requires_owner_and_idempotency_and_schedules_job(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    watchlist_api = importlib.import_module("price_monitor.api.v1.watchlist")
    enqueued_product_ids: list[str] = []
    monkeypatch.setattr(
        watchlist_api,
        "enqueue_fetch_product",
        enqueued_product_ids.append,
        raising=False,
    )

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
        product_url="https://example.com/refresh-me",
        target_price_minor=None,
        currency="RUB",
        request_id="req-create-refresh",
    )
    item = created.item
    path = f"/api/v1/watchlist/items/{item.id}/refresh"
    correct_body = json.dumps({"user_id": "wp-user-1"}, separators=(",", ":")).encode()

    missing_idempotency = client.post(
        path,
        content=correct_body,
        headers=signed_headers(
            "POST",
            path,
            correct_body,
            request_id="req-refresh-missing-idempotency",
            idempotency_key=None,
        ),
    )

    assert missing_idempotency.status_code == 400
    assert missing_idempotency.json()["error"]["code"] == "idempotency_key_required"

    wrong_body = json.dumps({"user_id": "wp-user-2"}, separators=(",", ":")).encode()
    wrong_owner = client.post(
        path,
        content=wrong_body,
        headers=signed_headers(
            "POST",
            path,
            wrong_body,
            request_id="req-refresh-wrong-owner",
            idempotency_key="idem-refresh-wrong-owner",
        ),
    )

    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["error"]["code"] == "watchlist_item_not_found"
    assert session.scalars(select(FetchJob)).all() == []

    headers = signed_headers(
        "POST",
        path,
        correct_body,
        request_id="req-refresh-correct-owner",
        idempotency_key="idem-refresh-correct-owner",
    )
    scheduled = client.post(path, content=correct_body, headers=headers)
    replayed = client.post(path, content=correct_body, headers=headers)

    assert scheduled.status_code == 202
    assert replayed.status_code == 202
    assert replayed.json() == scheduled.json()
    assert scheduled.json()["scheduled"] is True
    assert scheduled.json()["watchlist_item_id"] == item.id
    assert scheduled.json()["product_id"] == item.product_id
    jobs = session.scalars(select(FetchJob)).all()
    assert len(jobs) == 1
    assert jobs[0].product_id == item.product_id
    assert jobs[0].status == "queued"
    assert enqueued_product_ids == [item.product_id]


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
