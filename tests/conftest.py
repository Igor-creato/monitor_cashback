from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import price_monitor.db.models  # noqa: F401
from price_monitor.core.config import Settings
from price_monitor.core.security import build_signed_headers
from price_monitor.db.base import Base
from price_monitor.db.session import get_session
from price_monitor.main import create_app


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        hmac_secrets="test-secret",
        external_base_url="http://testserver",
    )
    app = create_app(settings)

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def disable_celery_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    from price_monitor.api.v1 import watchlist as watchlist_api

    monkeypatch.setattr(
        watchlist_api,
        "enqueue_fetch_product",
        lambda product_id, fetch_job_id=None: None,
        raising=False,
    )


def signed_headers(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    request_id: str = "req-test",
    idempotency_key: str | None = "idem-test",
) -> dict[str, str]:
    headers = build_signed_headers(
        secret="test-secret",
        method=method,
        path=path,
        body=body,
        request_id=request_id,
    )
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers
