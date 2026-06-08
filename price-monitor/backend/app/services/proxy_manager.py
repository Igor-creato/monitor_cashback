from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import (
    ProxyEndpoint,
    ProxyHealthEvent,
    ProxyLease,
    ProxyPool,
)

ACTIVE_LEASE_STATUS = "active"
REPORTED_LEASE_STATUS = "reported"
EXPIRED_LEASE_STATUS = "expired"
COOLDOWN_EVENT_TYPES = frozenset({"http_403", "http_429", "captcha"})
COOLDOWN_MINUTES = 15
DEFAULT_TTL_MINUTES = 30


def lease_proxy(
    source: str,
    purpose: str,
    job_id: str,
    *,
    session: Session | None = None,
    now: datetime | None = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> ProxyLease | None:
    if session is not None:
        return _lease_proxy(source, purpose, job_id, session, now, ttl_minutes)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _lease_proxy(source, purpose, job_id, owned_session, now, ttl_minutes)


def report_proxy_result(
    lease_token: str,
    status: str,
    event_type: str,
    response_ms: int | None,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> ProxyLease | None:
    if session is not None:
        return _report_proxy_result(
            lease_token,
            status,
            event_type,
            response_ms,
            session,
            now,
        )

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _report_proxy_result(
            lease_token,
            status,
            event_type,
            response_ms,
            owned_session,
            now,
        )


def release_expired_leases(
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> int:
    if session is not None:
        return _release_expired_leases(session, now)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _release_expired_leases(owned_session, now)


def _lease_proxy(
    source: str,
    purpose: str,
    job_id: str,
    session: Session,
    now: datetime | None,
    ttl_minutes: int,
) -> ProxyLease | None:
    now_utc = _as_utc_naive(now)
    endpoint = session.scalar(
        select(ProxyEndpoint)
        .join(ProxyPool)
        .where(
            ProxyPool.source == source,
            ProxyPool.purpose == purpose,
            ProxyPool.enabled.is_(True),
            ProxyEndpoint.enabled.is_(True),
            ProxyEndpoint.current_concurrency < ProxyEndpoint.max_concurrency,
            (ProxyEndpoint.cooldown_until.is_(None))
            | (ProxyEndpoint.cooldown_until <= now_utc),
        )
        .order_by(ProxyEndpoint.current_concurrency.asc(), ProxyEndpoint.id.asc())
        .limit(1)
    )
    if endpoint is None:
        return None

    endpoint.current_concurrency += 1
    lease = ProxyLease(
        lease_token=secrets.token_urlsafe(24),
        endpoint=endpoint,
        source=source,
        purpose=purpose,
        job_id=job_id,
        status=ACTIVE_LEASE_STATUS,
        leased_at=now_utc,
        expires_at=now_utc + timedelta(minutes=ttl_minutes),
    )
    session.add(lease)
    session.commit()
    session.refresh(lease)
    return lease


def _report_proxy_result(
    lease_token: str,
    status: str,
    event_type: str,
    response_ms: int | None,
    session: Session,
    now: datetime | None,
) -> ProxyLease | None:
    now_utc = _as_utc_naive(now)
    lease = session.scalar(
        select(ProxyLease).where(ProxyLease.lease_token == lease_token).limit(1)
    )
    if lease is None:
        return None

    if lease.status != ACTIVE_LEASE_STATUS:
        return lease

    endpoint = lease.endpoint
    session.add(
        ProxyHealthEvent(
            endpoint=endpoint,
            lease=lease,
            event_type=event_type,
            status=status,
            response_ms=response_ms,
        )
    )
    lease.status = REPORTED_LEASE_STATUS
    lease.reported_at = now_utc
    endpoint.current_concurrency = max(endpoint.current_concurrency - 1, 0)

    if event_type in COOLDOWN_EVENT_TYPES:
        endpoint.cooldown_until = now_utc + timedelta(minutes=COOLDOWN_MINUTES)

    session.commit()
    session.refresh(lease)
    return lease


def _release_expired_leases(session: Session, now: datetime | None) -> int:
    now_utc = _as_utc_naive(now)
    leases = session.scalars(
        select(ProxyLease).where(
            ProxyLease.status == ACTIVE_LEASE_STATUS,
            ProxyLease.expires_at <= now_utc,
        )
    ).all()

    for lease in leases:
        lease.status = EXPIRED_LEASE_STATUS
        lease.endpoint.current_concurrency = max(
            lease.endpoint.current_concurrency - 1,
            0,
        )

    session.commit()
    return len(leases)


def _as_utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
