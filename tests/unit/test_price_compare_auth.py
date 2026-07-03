import json
from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.core.config import Settings
from price_monitor.core.security import build_signed_headers
from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app


def test_search_requires_hmac_signature_when_secret_configured() -> None:
    client = TestClient(create_app(Settings(hmac_secrets="test-secret")))

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone", "city": "Москва", "limit": 10, "offset": 0},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_search_accepts_valid_hmac_signature_when_secret_configured() -> None:
    app = _app_with_empty_index(Settings(hmac_secrets="test-secret"))
    client = TestClient(app)
    payload = {"query": "iphone", "city": "Москва", "limit": 10, "offset": 0}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    headers = build_signed_headers(
        secret="test-secret",
        method="POST",
        path="/api/v1/search",
        body=body,
        request_id="request-1",
    )

    response = client.post("/api/v1/search", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def _app_with_empty_index(settings: Settings):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    return app
