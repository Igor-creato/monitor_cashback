from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from datetime import datetime, timedelta
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
    ImportedCollection,
    MarketplaceConnection,
    MarketplaceSessionSecret,
    MarketplaceSyncSession,
    ProductMatchGroup,
    ProductOffer,
    ProxyEndpoint,
    ProxyPool,
    SourceHealthEvent,
    SourceQuarantineState,
    Store,
    StoreSource,
    TrackedProduct,
)

SITE_ID = "savelloclub.test"
SECRET = "price-monitor-secret"
USER_ID = "wp:savelloclub.test:77"


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
    }


def test_admin_diagnostics_are_summarized_and_redacted(
    client: TestClient,
    db_session: Session,
) -> None:
    now = datetime.utcnow()
    store = Store(store_code="dns", display_name="DNS", enabled=True)
    tracked_product = TrackedProduct(
        source="ozon",
        external_product_id="ozon-1",
        canonical_url="https://ozon.ru/product/1",
        region_code="msk",
        product_name="Apple iPhone 15 Pro 256GB Black",
        last_price=Decimal("100000.00"),
        currency="RUB",
    )
    pool = ProxyPool(
        source="dns-api",
        purpose="price_fetch",
        tier="residential",
        enabled=True,
        priority=20,
        cost_per_request=Decimal("0.10000000"),
    )
    connection = MarketplaceConnection(
        site_id=SITE_ID,
        external_user_id=USER_ID,
        marketplace="ozon",
        status="connected",
        scope_json=["cart_read"],
        consent_version="price-assistant-session-v1",
        consented_at=now,
    )
    db_session.add_all([store, tracked_product, pool, connection])
    db_session.flush()
    db_session.add_all(
        [
            StoreSource(
                store=store,
                source_code="dns-api",
                display_name="DNS API",
                source_type="api",
                enabled=True,
                metadata_json={"matching": {"min_match_score": 75}},
            ),
            ProxyEndpoint(
                pool=pool,
                endpoint_ref="http://user:secret-password@proxy.example:8080",
                enabled=True,
                max_concurrency=5,
            ),
            FetchAttempt(
                tracked_product_id=tracked_product.id,
                source_code="dns-api",
                strategy="residential_proxy_http",
                proxy_pool_id=pool.id,
                status="failed",
                error_type="http_403",
                http_status=403,
                response_ms=500,
                cost_estimated=Decimal("0.100000"),
                product_data_found=False,
                price_found=False,
                image_found=False,
                created_at=now,
            ),
            SourceHealthEvent(
                source_code="dns-api",
                event_type="http_403",
                status_code=403,
                response_ms=500,
                created_at=now,
            ),
            SourceQuarantineState(
                source_code="dns-api",
                status="quarantined",
                reason="too_many_403",
                error_type="http_403",
                quarantined_until=now + timedelta(minutes=30),
            ),
            MarketplaceSessionSecret(
                connection=connection,
                encrypted_cookie_bundle="encrypted-secret-cookie",
                dek_ciphertext="wrapped-secret-dek",
                nonce="nonce",
                tag="tag",
                aad_json={},
                key_version="v1",
                bundle_fingerprint="fingerprint",
            ),
        ]
    )
    db_session.flush()
    collection = ImportedCollection(
        site_id=SITE_ID,
        external_user_id=USER_ID,
        connection=connection,
        source="ozon",
        region_code="msk",
        collection_type="cart",
        status="active",
    )
    match_group = ProductMatchGroup(
        tracked_product=tracked_product,
        match_key="feed:dns-api:iphone",
        confidence="high",
        label="same_product",
    )
    db_session.add_all([collection, match_group])
    db_session.flush()
    db_session.add_all(
        [
            MarketplaceSyncSession(
                connection=connection,
                collection=collection,
                site_id=SITE_ID,
                external_user_id=USER_ID,
                source="ozon",
                collection_type="cart",
                status="failed",
                started_at=now,
                finished_at=now,
                reason="login_required",
                item_count=1,
            ),
            ProductOffer(
                match_group=match_group,
                store=store,
                source_code="dns-api",
                external_product_id="dns-iphone",
                region_code="msk",
                product_url="https://www.dns-shop.ru/product/iphone",
                title="Apple iPhone 15 Pro 256GB Black",
                price=Decimal("95000.00"),
                currency="RUB",
                availability="in stock",
                match_confidence="high",
                match_label="same_product",
                raw_json={"match_score": 96, "secret_token": "token-value"},
            ),
        ]
    )
    db_session.commit()

    endpoints = [
        "/v1/price-assistant/admin/source-health",
        "/v1/price-assistant/admin/fetch-attempts",
        "/v1/price-assistant/admin/sync-diagnostics",
        "/v1/price-assistant/admin/quarantine",
        "/v1/price-assistant/admin/proxy-economics",
        "/v1/price-assistant/admin/matching-diagnostics",
    ]
    responses = [
        client.get(endpoint, headers=_signed_headers()) for endpoint in endpoints
    ]

    assert all(response.status_code == 200 for response in responses)
    combined = "".join(response.text for response in responses)
    assert "secret-password" not in combined
    assert "endpoint_ref" not in combined
    assert "encrypted-secret-cookie" not in combined
    assert "wrapped-secret-dek" not in combined
    assert "token-value" not in combined
    assert responses[0].json()["items"][0]["source_code"] == "dns-api"
    assert responses[1].json()["items"][0]["status"] == "failed"
    assert responses[2].json()["items"][0]["reason"] == "login_required"
    assert responses[3].json()["items"][0]["status"] == "quarantined"
    assert responses[4].json()["source_costs"][0]["source_code"] == "dns-api"
    assert responses[5].json()["items"][0]["match_score"] == 96
