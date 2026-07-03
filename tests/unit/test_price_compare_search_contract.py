from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app


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


def test_search_returns_not_found_warning_for_empty_index() -> None:
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["items"] == []
    assert payload["meta"]["total"] == 0
    assert payload["meta"]["warnings"] == ["Товаров не нашлось"]
