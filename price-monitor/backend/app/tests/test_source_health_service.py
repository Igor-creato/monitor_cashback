from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import SourceHealthEvent
from app.services.source_health import (
    get_source_health_summary,
    record_source_event,
)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.source_health as source_health

    monkeypatch.setattr(source_health, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _event_count(session: Session) -> int:
    return session.scalar(select(func.count(SourceHealthEvent.id))) or 0


def test_record_source_event_writes_health_event(db_session: Session) -> None:
    event = record_source_event(
        "testshop",
        "http_429",
        status_code=429,
        response_ms=250,
        session=db_session,
    )

    assert event.id is not None
    assert event.source_code == "testshop"
    assert event.event_type == "http_429"
    assert event.status_code == 429
    assert event.response_ms == 250
    assert event.created_at is not None
    assert _event_count(db_session) == 1


def test_source_health_summary_counts_success_and_failures(
    db_session: Session,
) -> None:
    record_source_event("testshop", "success", session=db_session)
    record_source_event("testshop", "timeout", session=db_session)
    record_source_event("testshop", "price_not_found", session=db_session)
    record_source_event("othershop", "timeout", session=db_session)

    summary = get_source_health_summary("testshop", session=db_session)

    assert summary.source_code == "testshop"
    assert summary.success_count == 1
    assert summary.price_fetch_failure_count == 2
    assert summary.cashback_api_error_count == 0
    assert summary.failure_count == 2
    assert summary.total_count == 3


def test_cashback_api_error_is_counted_separately_from_price_fetch_errors(
    db_session: Session,
) -> None:
    record_source_event("testshop", "parser_error", session=db_session)
    record_source_event("testshop", "cashback_api_error", session=db_session)
    record_source_event("testshop", "cashback_api_error", session=db_session)

    summary = get_source_health_summary("testshop", session=db_session)

    assert summary.success_count == 0
    assert summary.price_fetch_failure_count == 1
    assert summary.cashback_api_error_count == 2
    assert summary.failure_count == 3
    assert summary.total_count == 3
