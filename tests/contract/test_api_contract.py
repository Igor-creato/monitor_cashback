import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tests.conftest import signed_headers


def test_openapi_exposes_initial_wordpress_facing_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])

    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/watchlist/items" in paths
    assert "/api/v1/watchlist/items/{item_id}" in paths
    assert "/api/v1/products/{product_id}/price-history" in paths
    assert "/api/v1/sources/status" in paths


def test_watchlist_create_requires_hmac_and_idempotency_key(client: TestClient) -> None:
    response = client.post("/api/v1/watchlist/items", json={"url": "https://example.com/item"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_watchlist_create_returns_stable_contract_and_deduplicates(
    client: TestClient, session: Session
) -> None:
    del session
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
    assert second.status_code == 200
    assert second.json()["created"] is False


def test_idempotency_key_replay_returns_original_response(client: TestClient) -> None:
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


def test_health_and_read_endpoints_return_stable_empty_foundation_contract(
    client: TestClient,
) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["status"] == "ok"
    assert client.get("/api/v1/sources/status").json() == {"sources": []}

    history = client.get("/api/v1/products/missing-product/price-history").json()
    assert history == {"product_id": "missing-product", "points": []}
