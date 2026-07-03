from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from price_monitor.db.base import Base
from price_monitor.price_compare.live.repository import LiveSearchRunRepository


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_live_search_repository_creates_and_reads_run(db_session) -> None:
    repo = LiveSearchRunRepository(db_session)

    run = repo.create_run(
        query="телевизор",
        city="Пенза",
        stores=["fixture.test"],
        limit=20,
        timeout_seconds=120,
    )
    loaded = repo.get_run(run.run_id)

    assert loaded is not None
    assert loaded.query == "телевизор"
    assert loaded.city == "Пенза"
    assert loaded.status == "queued"
    assert loaded.result_payload == {}
