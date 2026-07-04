from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app
from price_monitor.price_compare.models import (
    AffiliateFeedSource,
    FeedImportRun,
    Offer,
    StoreSource,
)


def test_search_api_returns_sorted_active_store_offers() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as seed_session:
        seed_session.add(
            StoreSource(
                domain="ozon.ru",
                display_name="Ozon",
                active=True,
                source_type="custom",
                supports_region=False,
            )
        )
        seed_session.add_all(
            [
                Offer(
                    source="custom",
                    store_domain="ozon.ru",
                    external_id="expensive",
                    title="iPhone 15 128 Black",
                    normalized_title="iphone 15 128 black",
                    url="https://ozon.ru/product/expensive",
                    price=Decimal("90000.00"),
                    currency="RUB",
                    availability="in_stock",
                    region_supported=False,
                ),
                Offer(
                    source="custom",
                    store_domain="ozon.ru",
                    external_id="cheap",
                    title="iPhone 15 128 Blue",
                    normalized_title="iphone 15 128 blue",
                    url="{link}?dl=https%3A%2F%2Fozon.ru%2Fproduct%2Fcheap&m=5",
                    price=Decimal("80000.00"),
                    currency="RUB",
                    availability="in_stock",
                    region_supported=False,
                ),
            ]
        )
        seed_session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone 15 128", "city": "Москва", "limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 2
    assert [item["external_id"] for item in payload["items"]] == ["cheap", "expensive"]
    assert payload["items"][0]["price"] == 80000.0
    assert payload["items"][0]["url"] == "https://ozon.ru/product/cheap"
    assert payload["items"][0]["action_url"] == "https://ozon.ru/product/cheap"
    assert payload["items"][0]["region_supported"] is False
    assert payload["items"][0]["price_updated_at"] is not None
    assert payload["items"][0]["feed_updated_at"] is not None
    assert payload["meta"]["store_statuses"] == [
        {
            "store_domain": "ozon.ru",
            "status": "indexed",
            "offer_count": 2,
            "region_supported": False,
        }
    ]
    assert "{link}" not in response.text
    assert "secret" not in response.text.lower()


def test_search_api_exposes_affiliate_feed_freshness_without_claiming_realtime() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    feed_updated_at = datetime(2026, 7, 4, 12, 30, tzinfo=UTC)
    import_finished_at = datetime(2026, 7, 4, 13, 0, tzinfo=UTC)

    with Session(engine) as seed_session:
        seed_session.add(
            StoreSource(
                domain="merchant.test",
                display_name="Merchant",
                active=True,
                source_type="advcake",
                supports_region=False,
            )
        )
        seed_session.add(
            Offer(
                source="advcake_product_feed",
                store_domain="merchant.test",
                external_id="feed-offer-1",
                title="Redmi Note 13",
                normalized_title="redmi note 13",
                url="https://merchant.test/p/1",
                price=Decimal("15990.00"),
                currency="RUB",
                availability="unknown",
                region_supported=False,
            )
        )
        seed_session.add(
            AffiliateFeedSource(
                network="advcake",
                store_domain="merchant.test",
                offer_id="",
                feed_id="feed-yml",
                display_name="Merchant feed",
                format="xml",
                feed_url_hash="b" * 64,
                feed_url_secret=True,
                descriptor_payload={"feed_url": "[redacted]"},
                active=True,
                last_feed_updated_at=feed_updated_at,
            )
        )
        seed_session.flush()
        feed = seed_session.query(AffiliateFeedSource).one()
        seed_session.add(
            FeedImportRun(
                feed_source_id=feed.id,
                status="success",
                started_at=import_finished_at,
                finished_at=import_finished_at,
                feed_updated_at=feed_updated_at,
                created_count=1,
                updated_count=0,
                skipped_count=0,
                quarantined_count=0,
            )
        )
        seed_session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        json={"query": "redmi note 13", "city": "Пенза", "limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["source"] == "advcake_product_feed"
    assert item["feed_updated_at"] == "2026-07-04T12:30:00Z"
    assert item["freshness"] == {
        "mode": "affiliate_feed",
        "realtime": False,
        "coverage": "partner_feed",
        "feed_updated_at": "2026-07-04T12:30:00Z",
        "import_finished_at": "2026-07-04T13:00:00Z",
        "import_status": "success",
        "warnings": ["FEED_NOT_REALTIME", "REGION_NOT_GUARANTEED"],
    }
    assert "feed-yml" not in response.text
    assert "feed_url" not in response.text.lower()


def test_search_api_returns_safe_error_when_index_is_unavailable() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone 15 128", "city": "Москва", "limit": 10, "offset": 0},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "SEARCH_BACKEND_UNAVAILABLE"
    assert "price_compare_offers" not in response.text
