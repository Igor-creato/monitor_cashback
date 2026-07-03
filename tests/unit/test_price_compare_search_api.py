from collections.abc import Iterator
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app
from price_monitor.price_compare.models import Offer, StoreSource


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
                    url="https://ozon.ru/product/cheap",
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
    assert payload["items"][0]["region_supported"] is False


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
