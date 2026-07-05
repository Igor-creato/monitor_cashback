from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from price_monitor.core.config import get_settings
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


def test_live_search_worker_prioritizes_unavailable_store_warning(db_session, monkeypatch) -> None:
    monkeypatch.delenv("PRICE_MONITOR_DECODO_BASIC_AUTH_TOKEN", raising=False)
    get_settings.cache_clear()
    db_session.add(
        StoreSource(
            domain="citilink.ru",
            display_name="Citilink",
            active=True,
            source_type="managed_provider",
            source_config={
                "provider": "decodo",
                "live_search_url_template": "https://www.citilink.ru/search/?text={query}",
                "parser": "citilink_search_v1",
            },
            supports_region=True,
        )
    )
    db_session.commit()
    repo = LiveSearchRunRepository(db_session)
    run = repo.create_run(
        query="телевизор",
        city="Пенза",
        stores=["citilink.ru"],
        limit=10,
        timeout_seconds=120,
    )

    result = run_live_search.run(run.run_id)
    loaded = repo.get_run(run.run_id)

    assert result["status"] == "failed"
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.result_payload["store_statuses"][0]["warnings"] == ["decodo_not_configured"]
    assert loaded.result_payload["meta"]["warnings"][0] == "Часть магазинов недоступна"


def test_live_search_worker_overfetches_before_relevance_filtering(db_session) -> None:
    accessories = [
        {
            "title": f"Чехол для Xiaomi Redmi Note 13 #{index}",
            "price": 499 + index,
            "url": f"https://fixture.test/case-{index}",
            "availability": "in_stock",
        }
        for index in range(1, 6)
    ]
    db_session.add(
        StoreSource(
            domain="fixture.test",
            display_name="Fixture Store",
            active=True,
            source_type="custom",
            source_config={
                "live_fixture_items": [
                    *accessories,
                    {
                        "title": "Смартфон Xiaomi Redmi Note 13 8/256GB",
                        "price": 17990,
                        "url": "https://fixture.test/redmi-note-13",
                        "availability": "in_stock",
                        "category": "Смартфоны",
                    },
                ]
            },
            supports_region=True,
        )
    )
    db_session.commit()
    repo = LiveSearchRunRepository(db_session)
    run = repo.create_run(
        query="redmi note 13",
        city="Москва",
        stores=["fixture.test"],
        limit=5,
        timeout_seconds=120,
    )

    result = run_live_search.run(run.run_id)
    loaded = repo.get_run(run.run_id)

    assert result["status"] == "ok"
    assert loaded is not None
    assert loaded.result_payload["items"][0]["title"] == "Смартфон Xiaomi Redmi Note 13 8/256GB"
