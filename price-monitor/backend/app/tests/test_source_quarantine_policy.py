from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import ProxyHealthEvent, SourceHealthEvent
from app.services.source_quarantine import (
    apply_source_quarantine_policy,
    get_effective_source_quarantine_state,
)

NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.source_quarantine as source_quarantine

    monkeypatch.setattr(source_quarantine, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _record_health(
    session: Session,
    source_code: str,
    event_type: str,
    created_at: datetime,
) -> None:
    session.add(
        SourceHealthEvent(
            source_code=source_code,
            event_type=event_type,
            created_at=created_at.replace(tzinfo=None),
        )
    )
    session.commit()


def _proxy_health_count(session: Session) -> int:
    return session.scalar(select(func.count(ProxyHealthEvent.id))) or 0


def test_many_429_moves_source_to_cooldown(db_session: Session) -> None:
    for minutes_ago in (20, 10, 1):
        _record_health(
            db_session,
            "testshop",
            "http_429",
            NOW - timedelta(minutes=minutes_ago),
        )

    state = apply_source_quarantine_policy(
        "testshop",
        "http_429",
        session=db_session,
        now=NOW,
    )

    assert state.status == "cooldown"
    assert state.reason == "too_many_429"
    assert state.error_type == "http_429"
    assert state.quarantined_until == (NOW + timedelta(minutes=15)).replace(tzinfo=None)


def test_many_403_moves_source_to_quarantine(db_session: Session) -> None:
    for minutes_ago in (25, 12, 2):
        _record_health(
            db_session,
            "testshop",
            "http_403",
            NOW - timedelta(minutes=minutes_ago),
        )

    state = apply_source_quarantine_policy(
        "testshop",
        "http_403",
        session=db_session,
        now=NOW,
    )

    assert state.status == "quarantined"
    assert state.reason == "too_many_403"
    assert state.error_type == "http_403"
    assert state.quarantined_until == (NOW + timedelta(hours=24)).replace(tzinfo=None)


def test_captcha_detected_moves_source_to_quarantine(db_session: Session) -> None:
    state = apply_source_quarantine_policy(
        "testshop",
        "captcha_detected",
        session=db_session,
        now=NOW,
    )

    assert state.status == "quarantined"
    assert state.reason == "captcha_detected"
    assert state.error_type == "captcha_detected"
    assert state.quarantined_until == (NOW + timedelta(hours=24)).replace(tzinfo=None)


def test_many_parser_errors_mark_parser_issue_without_proxy_ban(
    db_session: Session,
) -> None:
    for minutes_ago in (20, 10, 1):
        _record_health(
            db_session,
            "testshop",
            "parser_error",
            NOW - timedelta(minutes=minutes_ago),
        )

    state = apply_source_quarantine_policy(
        "testshop",
        "parser_error",
        session=db_session,
        now=NOW,
    )

    assert state.status == "active"
    assert state.reason == "parser_issue"
    assert state.error_type == "parser_error"
    assert state.quarantined_until is None
    assert _proxy_health_count(db_session) == 0


def test_expired_quarantine_returns_active(db_session: Session) -> None:
    state = apply_source_quarantine_policy(
        "testshop",
        "captcha_detected",
        session=db_session,
        now=NOW,
    )
    state.quarantined_until = (NOW - timedelta(minutes=1)).replace(tzinfo=None)
    db_session.commit()

    effective = get_effective_source_quarantine_state(
        "testshop",
        session=db_session,
        now=NOW,
    )

    assert effective.status == "active"
    assert effective.reason is None
    assert effective.error_type is None
    assert effective.quarantined_until is None


def test_disabled_source_does_not_activate_automatically(db_session: Session) -> None:
    state = apply_source_quarantine_policy(
        "testshop",
        "captcha_detected",
        session=db_session,
        now=NOW,
    )
    state.status = "disabled"
    state.reason = "manual_disable"
    state.quarantined_until = (NOW - timedelta(days=1)).replace(tzinfo=None)
    db_session.commit()

    effective = get_effective_source_quarantine_state(
        "testshop",
        session=db_session,
        now=NOW,
    )

    assert effective.status == "disabled"
    assert effective.reason == "manual_disable"
