from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime

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
    ImportedCollection,
    MarketplaceConnection,
    MarketplaceSessionSecret,
)

ADMIN_KEY = "admin-test-key"
SITE_ID = "savelloclub.ru"
USER_ID = "wp:savelloclub.ru:123"


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
    monkeypatch.setattr(config.settings, "admin_api_key", SecretStr(ADMIN_KEY))
    monkeypatch.setattr(
        config.settings,
        "marketplace_session_keyring",
        SecretStr("v1:" + base64.b64encode(b"k" * 32).decode()),
    )
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _admin_headers(key: str = ADMIN_KEY) -> dict[str, str]:
    return {"ADMIN_API_KEY": key}


def test_admin_foundation_endpoints_require_admin_key(client: TestClient) -> None:
    endpoints = [
        ("get", "/admin/stores", None),
        ("post", "/admin/stores", {"store_code": "dns", "display_name": "DNS"}),
        ("patch", "/admin/stores/1", {"enabled": False}),
        ("post", "/admin/stores/1/sources", {"source_code": "dns-feed"}),
        ("get", "/admin/imports", None),
        ("get", "/admin/diagnostics", None),
    ]

    for method, endpoint, payload in endpoints:
        if payload is None:
            response = getattr(client, method)(endpoint)
        else:
            response = getattr(client, method)(endpoint, json=payload)
        assert response.status_code == 401


def test_admin_can_manage_stores_and_sources(client: TestClient) -> None:
    create_store = client.post(
        "/admin/stores",
        headers=_admin_headers(),
        json={
            "store_code": "dns",
            "display_name": "DNS",
            "enabled": True,
            "homepage_url": "https://dns-shop.local",
        },
    )
    assert create_store.status_code == 200
    assert create_store.json()["store_id"] == 1

    create_source = client.post(
        "/admin/stores/1/sources",
        headers=_admin_headers(),
        json={
            "source_code": "dns-feed",
            "display_name": "DNS Feed",
            "enabled": True,
            "source_type": "feed",
            "metadata_json": {
                "matching": {
                    "min_match_score": 70,
                    "likely_threshold": 84,
                    "exact_threshold": 96,
                }
            },
        },
    )
    assert create_source.status_code == 200
    assert create_source.json()["source_id"] > 0
    assert create_source.json()["metadata_json"] == {
        "matching": {
            "min_match_score": 70,
            "likely_threshold": 84,
            "exact_threshold": 96,
        }
    }

    patch_store = client.patch(
        "/admin/stores/1",
        headers=_admin_headers(),
        json={"enabled": False, "display_name": "Changed DNS"},
    )
    stores = client.get("/admin/stores", headers=_admin_headers())

    assert patch_store.status_code == 200
    assert patch_store.json()["enabled"] is False
    assert patch_store.json()["display_name"] == "Changed DNS"
    assert stores.status_code == 200
    dns_feed_source = next(
        source
        for source in stores.json()["items"][0]["sources"]
        if source["source_code"] == "dns-feed"
    )
    assert dns_feed_source["metadata_json"] == {
        "matching": {
            "min_match_score": 70,
            "likely_threshold": 84,
            "exact_threshold": 96,
        }
    }


def test_admin_imports_and_diagnostics_are_read_only_and_redacted(
    client: TestClient,
    db_session: Session,
) -> None:
    connection = MarketplaceConnection(
        site_id=SITE_ID,
        external_user_id=USER_ID,
        marketplace="ozon",
        status="connected",
        scope_json=["cart_read"],
        consent_version="price-assistant-session-v1",
        consented_at=datetime(2026, 6, 15, 10, 0, 0),
    )
    db_session.add(connection)
    db_session.flush()
    db_session.add(
        MarketplaceSessionSecret(
            connection=connection,
            encrypted_cookie_bundle="encrypted-secret-cookie",
            dek_ciphertext="wrapped-secret-dek",
            nonce="nonce",
            tag="tag",
            aad_json={},
            key_version="v1",
            bundle_fingerprint="fingerprint",
        )
    )
    db_session.add(
        ImportedCollection(
            site_id=SITE_ID,
            external_user_id=USER_ID,
            connection=connection,
            collection_type="cart",
            source="ozon",
            status="active",
        )
    )
    db_session.commit()

    imports = client.get("/admin/imports", headers=_admin_headers())
    diagnostics = client.get("/admin/diagnostics", headers=_admin_headers())

    assert imports.status_code == 200
    assert diagnostics.status_code == 200
    combined = imports.text + diagnostics.text
    assert "encrypted-secret-cookie" not in combined
    assert "wrapped-secret-dek" not in combined
    assert "secret-cookie" not in combined
    assert imports.json()["items"][0]["collection_type"] == "cart"
    assert diagnostics.json()["marketplace_connections_total"] == 1
    assert diagnostics.json()["encrypted_session_secrets_total"] == 1
