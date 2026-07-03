from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.api.v1 import live_search
from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app


def _client_with_session() -> TestClient:
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
    return TestClient(app)


def test_live_search_rejects_empty_city(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_HMAC_SECRETS", "")
    client = _client_with_session()

    response = client.post(
        "/api/v1/live-search/runs",
        json={"query": "телевизор", "city": "", "stores": [], "limit": 20},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_CITY"


def test_live_search_accepts_valid_request_with_run_id(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_HMAC_SECRETS", "")
    delayed: list[str] = []

    class FakeTask:
        @staticmethod
        def delay(run_id: str) -> None:
            delayed.append(run_id)

    monkeypatch.setattr(live_search, "run_live_search", FakeTask, raising=False)
    client = _client_with_session()

    response = client.post(
        "/api/v1/live-search/runs",
        json={"query": "телевизор", "city": "Пенза", "stores": ["fixture.test"], "limit": 20},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["run_id"]
    assert payload["poll_url"].endswith(payload["run_id"])
    assert delayed == [payload["run_id"]]


def test_live_search_poll_returns_not_found_for_unknown_run(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_HMAC_SECRETS", "")
    client = _client_with_session()

    response = client.get("/api/v1/live-search/runs/missing")

    assert response.status_code == 404
    assert response.json()["error_code"] == "LIVE_SEARCH_NOT_FOUND"
