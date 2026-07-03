from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.price_compare.live.repository import LiveSearchRunRepository
from price_monitor.price_compare.models import StoreSource
from price_monitor.workers.tasks.live_search import run_live_search


@pytest.fixture
def db_session(monkeypatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(
        "price_monitor.workers.tasks.live_search.get_session_factory",
        lambda: factory,
    )
    with factory() as session:
        yield session


def test_live_search_worker_persists_completed_fixture_results(db_session) -> None:
    db_session.add(
        StoreSource(
            domain="fixture.test",
            display_name="Fixture Store",
            active=True,
            source_type="custom",
            source_config={
                "live_fixture_items": [
                    {
                        "title": "Телевизор TCL 55C645",
                        "price": 39990,
                        "url": "https://fixture.test/tcl-55",
                        "availability": "in_stock",
                    }
                ]
            },
            supports_region=True,
        )
    )
    db_session.commit()
    repo = LiveSearchRunRepository(db_session)
    run = repo.create_run(
        query="телевизор",
        city="Пенза",
        stores=["fixture.test"],
        limit=10,
        timeout_seconds=120,
    )

    result = run_live_search.run(run.run_id)
    loaded = repo.get_run(run.run_id)

    assert result["status"] == "ok"
    assert loaded is not None
    assert loaded.status == "ok"
    assert loaded.result_payload["items"]
