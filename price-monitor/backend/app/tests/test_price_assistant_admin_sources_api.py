from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config, incoming_hmac
from app.main import app
from app.models.monitoring import AuditEvent, StoreSource

SITE_ID = "savelloclub.test"
SECRET = "price-monitor-secret"


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
    monkeypatch.setattr(incoming_hmac, "current_unix_time", lambda: 1781516800)
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _signed_headers(
    raw_body: str = "",
    timestamp: str = "1781516800",
) -> dict[str, str]:
    signature = hmac.new(
        SECRET.encode(),
        f"{timestamp}.{raw_body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Savello-Site": SITE_ID,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": signature,
        "Content-Type": "application/json",
    }


def _json_request(
    client: TestClient,
    method: str,
    path: str,
    payload: dict,
):
    raw_body = json.dumps(payload, separators=(",", ":"))
    return getattr(client, method)(
        path,
        content=raw_body,
        headers=_signed_headers(raw_body),
    )


def _create_store(client: TestClient) -> int:
    response = _json_request(
        client,
        "post",
        "/v1/price-assistant/admin/stores",
        {
            "store_code": "dns",
            "display_name": "DNS",
            "enabled": True,
            "homepage_url": "https://www.dns-shop.ru",
        },
    )
    assert response.status_code == 200
    return int(response.json()["store_id"])


def test_price_assistant_admin_routes_require_hmac(client: TestClient) -> None:
    response = client.get("/v1/price-assistant/admin/stores")

    assert response.status_code == 401


def test_admin_store_source_policy_fields_round_trip_and_audit(
    client: TestClient,
    db_session: Session,
) -> None:
    store_id = _create_store(client)
    payload = {
        "source_code": "dns-api",
        "display_name": "DNS API",
        "enabled": True,
        "source_type": "api",
        "domains": ["dns-shop.ru", "www.dns-shop.ru"],
        "search_template": "https://www.dns-shop.ru/search/?q={query}&city={region}",
        "region_support": ["msk", "spb"],
        "priority": 40,
        "extraction_mode": "json",
        "proxy_tier_policy": "cheap_first",
        "min_fetch_interval_minutes": 90,
        "matching_threshold": 76,
        "cashback_merchant_mapping": {
            "merchant_id": "dns",
            "merchant_name": "DNS",
        },
    }

    create_source = _json_request(
        client,
        "post",
        f"/v1/price-assistant/admin/stores/{store_id}/sources",
        payload,
    )
    stores = client.get(
        "/v1/price-assistant/admin/stores",
        headers=_signed_headers(),
    )

    assert create_source.status_code == 200
    assert stores.status_code == 200
    source = stores.json()["items"][0]["sources"][0]
    assert source["source_code"] == "dns-api"
    assert source["domains"] == ["dns-shop.ru", "www.dns-shop.ru"]
    assert (
        source["search_template"]
        == "https://www.dns-shop.ru/search/?q={query}&city={region}"
    )
    assert source["region_support"] == ["msk", "spb"]
    assert source["priority"] == 40
    assert source["extraction_mode"] == "json"
    assert source["proxy_tier_policy"] == "cheap_first"
    assert source["min_fetch_interval_minutes"] == 90
    assert source["matching_threshold"] == 76
    assert source["cashback_merchant_mapping"] == {
        "merchant_id": "dns",
        "merchant_name": "DNS",
    }
    assert source["metadata_json"]["matching"]["min_match_score"] == 76

    stored_source = db_session.scalar(select(StoreSource))
    assert stored_source is not None
    assert stored_source.matching_threshold == 76
    assert stored_source.metadata_json["matching"]["min_match_score"] == 76

    audit_events = db_session.scalars(
        select(AuditEvent).order_by(AuditEvent.id.asc())
    ).all()
    assert [event.event_type for event in audit_events] == [
        "price_assistant_store_created",
        "price_assistant_source_created",
    ]
    assert all(event.actor_type == "admin" for event in audit_events)


def test_secret_like_policy_values_are_rejected_without_echoing_secret(
    client: TestClient,
) -> None:
    store_id = _create_store(client)
    payload = {
        "source_code": "bad-source",
        "display_name": "Bad Source",
        "source_type": "api",
        "domains": ["example.test"],
        "search_template": "https://api.example.test/search?api_key=secret-token-value&q={query}",
        "region_support": ["default"],
        "priority": 10,
        "extraction_mode": "json",
        "proxy_tier_policy": "none",
        "min_fetch_interval_minutes": 60,
        "matching_threshold": 65,
        "cashback_merchant_mapping": {"merchant_id": "bad"},
    }

    response = _json_request(
        client,
        "post",
        f"/v1/price-assistant/admin/stores/{store_id}/sources",
        payload,
    )

    assert response.status_code == 422
    assert "secret-token-value" not in response.text
