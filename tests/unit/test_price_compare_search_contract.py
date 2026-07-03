from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app
from price_monitor.price_compare.models import StoreSource


def test_search_rejects_empty_city_with_safe_error() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone 15 128", "city": "", "limit": 50, "offset": 0},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "INVALID_CITY"
    assert "traceback" not in response.text.lower()


def test_search_returns_source_error_when_no_active_stores_are_configured() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone 15 128", "city": "Москва", "limit": 50, "offset": 0},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "SOURCE_UNAVAILABLE"
    assert payload["message"] == "Источники поиска не настроены."


def test_search_returns_index_error_when_active_stores_have_no_imported_offers() -> None:
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
        seed_session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/search",
        json={"query": "телевизор", "city": "Пенза", "limit": 50, "offset": 0},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "SEARCH_INDEX_EMPTY"
    assert payload["message"] == "Индекс поиска пуст. Запустите импорт товаров."
