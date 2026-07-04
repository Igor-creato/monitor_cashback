from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app
from price_monitor.price_compare.models import (
    AffiliateFeedSource,
    FeedImportRun,
    ImportStatus,
    Offer,
)


def _client_with_session(engine) -> TestClient:
    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_store_admin_api_creates_lists_updates_and_deactivates_store() -> None:
    engine = _engine()
    client = _client_with_session(engine)

    create_response = client.post(
        "/api/v1/stores",
        json={
            "domain": "https://www.ozon.ru/",
            "display_name": "Ozon",
            "aliases": ["ozon.ru", "www.ozon.ru", "ozon.com"],
            "logo_url": "https://cdn.example.test/ozon.svg",
            "source_type": "custom",
            "source_config": {"feed_identifier": "fixture-ozon"},
            "priority": 10,
            "supports_region": False,
            "fallback_behavior": "status_only",
            "active": True,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["domain"] == "ozon.ru"
    assert created["display_name"] == "Ozon"
    assert created["aliases"] == ["ozon.com"]
    assert created["source_config"] == {"feed_identifier": "fixture-ozon"}
    assert created["offer_count"] == 0
    assert created["import_status"] is None

    with Session(engine) as session:
        session.add(
            Offer(
                source="custom",
                store_domain="ozon.ru",
                external_id="iphone-15",
                title="iPhone 15 128",
                normalized_title="iphone 15 128",
                url="https://ozon.ru/product/iphone-15",
                price=Decimal("80000.00"),
                currency="RUB",
                availability="in_stock",
                region_supported=False,
            )
        )
        session.add(
            ImportStatus(
                source="custom",
                store_domain="ozon.ru",
                status="success",
                imported_count=1,
                skipped_count=0,
            )
        )
        session.commit()

    list_response = client.get("/api/v1/stores")
    assert list_response.status_code == 200
    listed = list_response.json()["items"][0]
    assert listed["domain"] == "ozon.ru"
    assert listed["offer_count"] == 1
    assert listed["import_status"]["status"] == "success"
    assert listed["import_status"]["imported_count"] == 1

    update_response = client.patch(
        f"/api/v1/stores/{created['id']}",
        json={
            "display_name": "Ozon RU",
            "active": False,
            "priority": 20,
            "supports_region": True,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["display_name"] == "Ozon RU"
    assert updated["active"] is False
    assert updated["priority"] == 20
    assert updated["supports_region"] is True

    delete_response = client.delete(f"/api/v1/stores/{created['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["active"] is False


def test_store_admin_api_rejects_private_logo_url() -> None:
    client = _client_with_session(_engine())

    response = client.post(
        "/api/v1/stores",
        json={
            "domain": "wildberries.ru",
            "display_name": "Wildberries",
            "logo_url": "http://127.0.0.1/logo.svg",
            "source_type": "custom",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "INVALID_LOGO_URL"


def test_store_admin_api_accepts_live_search_source_type() -> None:
    client = _client_with_session(_engine())

    response = client.post(
        "/api/v1/stores",
        json={
            "domain": "fixture.test",
            "display_name": "Fixture",
            "source_type": "direct_http",
            "source_config": {
                "live_search_url_template": "https://fixture.test/search?q={query}&city={city}"
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "direct_http"
    assert payload["source_config"]["live_search_url_template"].startswith("https://fixture.test")


def test_store_admin_api_includes_affiliate_feed_health_without_secret_payloads() -> None:
    engine = _engine()
    client = _client_with_session(engine)

    create_response = client.post(
        "/api/v1/stores",
        json={
            "domain": "merchant.test",
            "display_name": "Merchant",
            "source_type": "admitad",
            "source_config": {"feed_identifier": "public-admin-id"},
        },
    )
    assert create_response.status_code == 201
    store_id = create_response.json()["id"]
    feed_updated_at = datetime(2026, 7, 4, 12, 30, tzinfo=UTC)
    finished_at = datetime(2026, 7, 4, 13, 0, tzinfo=UTC)

    with Session(engine) as session:
        session.add(
            AffiliateFeedSource(
                network="admitad",
                store_domain="merchant.test",
                offer_id="campaign-10",
                feed_id="feed-secret-id",
                display_name="Merchant feed",
                format="csv",
                feed_url_hash="a" * 64,
                feed_url_secret=True,
                descriptor_payload={"feed_url": "[redacted]", "products_count": 10},
                active=True,
                last_feed_updated_at=feed_updated_at,
            )
        )
        session.flush()
        feed = session.scalars(select(AffiliateFeedSource)).one()
        session.add(
            FeedImportRun(
                feed_source_id=feed.id,
                status="success",
                started_at=finished_at,
                finished_at=finished_at,
                feed_updated_at=feed_updated_at,
                created_count=7,
                updated_count=2,
                skipped_count=1,
                quarantined_count=0,
            )
        )
        session.commit()

    response = client.get("/api/v1/stores")
    assert response.status_code == 200
    store = next(item for item in response.json()["items"] if item["id"] == store_id)

    assert store["feed_health"] == {
        "active_feed_count": 1,
        "last_import_status": "success",
        "last_import_finished_at": "2026-07-04T13:00:00Z",
        "last_feed_updated_at": "2026-07-04T12:30:00Z",
        "created_count": 7,
        "updated_count": 2,
        "skipped_count": 1,
        "quarantined_count": 0,
        "last_error_code": None,
    }
    assert "feed-secret-id" not in repr(store["feed_health"])
    assert "feed_url" not in repr(store["feed_health"]).lower()
