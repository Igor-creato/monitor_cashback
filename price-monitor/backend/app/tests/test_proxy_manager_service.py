from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import ProxyEndpoint, ProxyHealthEvent, ProxyPool
from app.services.proxy_manager import (
    lease_proxy,
    release_expired_leases,
    report_proxy_result,
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

    import app.services.proxy_manager as proxy_manager

    monkeypatch.setattr(proxy_manager, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _add_proxy_endpoint(
    session: Session,
    *,
    source: str = "testshop",
    purpose: str = "price_fetch",
    pool_enabled: bool = True,
    endpoint_enabled: bool = True,
    max_concurrency: int = 1,
    current_concurrency: int = 0,
    cooldown_until: datetime | None = None,
) -> ProxyEndpoint:
    pool = ProxyPool(
        source=source,
        purpose=purpose,
        enabled=pool_enabled,
    )
    endpoint = ProxyEndpoint(
        pool=pool,
        endpoint_ref="local-proxy-1",
        enabled=endpoint_enabled,
        max_concurrency=max_concurrency,
        current_concurrency=current_concurrency,
        cooldown_until=cooldown_until,
    )
    session.add(endpoint)
    session.commit()
    session.refresh(endpoint)
    return endpoint


def test_active_proxy_is_leased(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    endpoint = _add_proxy_endpoint(db_session)

    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-1",
        session=db_session,
        now=now,
    )

    assert lease is not None
    assert lease.endpoint_id == endpoint.id
    assert lease.source == "testshop"
    assert lease.purpose == "price_fetch"
    assert lease.job_id == "job-1"
    assert lease.status == "active"
    assert lease.lease_token
    assert lease.leased_at == now.replace(tzinfo=None)
    assert lease.expires_at == (now + timedelta(minutes=30)).replace(tzinfo=None)

    db_session.refresh(endpoint)
    assert endpoint.current_concurrency == 1


def test_disabled_proxy_is_not_leased(db_session: Session) -> None:
    endpoint = _add_proxy_endpoint(db_session, endpoint_enabled=False)

    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-1",
        session=db_session,
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
    )

    assert lease is None
    db_session.refresh(endpoint)
    assert endpoint.current_concurrency == 0


def test_concurrency_limit_is_respected(db_session: Session) -> None:
    endpoint = _add_proxy_endpoint(
        db_session,
        max_concurrency=1,
        current_concurrency=1,
    )

    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-2",
        session=db_session,
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
    )

    assert lease is None
    db_session.refresh(endpoint)
    assert endpoint.current_concurrency == 1


def test_report_success_releases_proxy(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    endpoint = _add_proxy_endpoint(db_session)
    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-1",
        session=db_session,
        now=now,
    )
    assert lease is not None

    reported = report_proxy_result(
        lease.lease_token,
        "success",
        "success",
        120,
        session=db_session,
        now=now + timedelta(seconds=5),
    )

    assert reported is not None
    assert reported.status == "reported"
    assert reported.reported_at == (now + timedelta(seconds=5)).replace(tzinfo=None)

    db_session.refresh(endpoint)
    assert endpoint.current_concurrency == 0

    event = db_session.scalar(select(ProxyHealthEvent))
    assert event is not None
    assert event.endpoint_id == endpoint.id
    assert event.lease_id == lease.id
    assert event.event_type == "success"
    assert event.status == "success"
    assert event.response_ms == 120


def test_http_429_moves_proxy_to_cooldown(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    endpoint = _add_proxy_endpoint(db_session)
    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-1",
        session=db_session,
        now=now,
    )
    assert lease is not None

    report_proxy_result(
        lease.lease_token,
        "failed",
        "http_429",
        300,
        session=db_session,
        now=now,
    )

    db_session.refresh(endpoint)
    assert endpoint.current_concurrency == 0
    assert endpoint.cooldown_until == (now + timedelta(minutes=15)).replace(tzinfo=None)

    cooldown_lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-2",
        session=db_session,
        now=now + timedelta(minutes=1),
    )
    assert cooldown_lease is None


def test_expired_lease_is_released(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    endpoint = _add_proxy_endpoint(db_session)
    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-1",
        session=db_session,
        now=now,
        ttl_minutes=5,
    )
    assert lease is not None

    released_count = release_expired_leases(
        session=db_session,
        now=now + timedelta(minutes=6),
    )

    assert released_count == 1
    db_session.refresh(endpoint)
    db_session.refresh(lease)
    assert endpoint.current_concurrency == 0
    assert lease.status == "expired"


def test_repeated_report_does_not_break_counters(db_session: Session) -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    endpoint = _add_proxy_endpoint(db_session)
    lease = lease_proxy(
        "testshop",
        "price_fetch",
        "job-1",
        session=db_session,
        now=now,
    )
    assert lease is not None

    first_report = report_proxy_result(
        lease.lease_token,
        "success",
        "success",
        100,
        session=db_session,
        now=now,
    )
    second_report = report_proxy_result(
        lease.lease_token,
        "success",
        "success",
        110,
        session=db_session,
        now=now + timedelta(seconds=1),
    )

    assert first_report is not None
    assert second_report is not None
    assert second_report.status == "reported"

    db_session.refresh(endpoint)
    assert endpoint.current_concurrency == 0
    assert len(db_session.scalars(select(ProxyHealthEvent)).all()) == 1
