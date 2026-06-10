from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
from app.models.monitoring import (
    PROXY_POOL_TIER_ORDER,
    PROXY_POOL_TIER_VALUES,
    ProxyEndpoint,
    ProxyHealthEvent,
    ProxyPool,
)

BAN_SCORE_THRESHOLD = 50
LOW_SUCCESS_RATE_THRESHOLD = 0.5
BAN_EVENT_TYPES = frozenset({"http_403", "http_429", "captcha"})

ProxyPoolErrorType = Literal["no_eligible_pool"]
ProxyEndpointErrorType = Literal["no_eligible_endpoint"]


class NoEligibleProxyPoolError(Exception):
    def __init__(
        self,
        error_type: ProxyPoolErrorType = "no_eligible_pool",
        message: str | None = None,
    ) -> None:
        self.error_type = error_type
        super().__init__(message or error_type)


class NoEligibleProxyEndpointError(Exception):
    def __init__(
        self,
        error_type: ProxyEndpointErrorType = "no_eligible_endpoint",
        message: str | None = None,
    ) -> None:
        self.error_type = error_type
        super().__init__(message or error_type)


def select_proxy_pool(
    source_code: str,
    required_tier: str,
    max_cost: Decimal | None,
    region_code: str | None = None,
    *,
    require_sticky: bool = False,
    session: Session | None = None,
) -> ProxyPool:
    if session is not None:
        return _select_proxy_pool(
            source_code,
            required_tier,
            max_cost,
            region_code,
            require_sticky,
            session,
        )

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _select_proxy_pool(
            source_code,
            required_tier,
            max_cost,
            region_code,
            require_sticky,
            owned_session,
        )


def select_proxy_endpoint(
    pool_id: int,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> ProxyEndpoint:
    if session is not None:
        return _select_proxy_endpoint(pool_id, session, now)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _select_proxy_endpoint(pool_id, owned_session, now)


def update_proxy_quality_metrics(
    proxy_endpoint_id: int,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> ProxyEndpoint | None:
    if session is not None:
        return _update_proxy_quality_metrics(proxy_endpoint_id, session, now)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _update_proxy_quality_metrics(proxy_endpoint_id, owned_session, now)


def _select_proxy_pool(
    source_code: str,
    required_tier: str,
    max_cost: Decimal | None,
    region_code: str | None,
    require_sticky: bool,
    session: Session,
) -> ProxyPool:
    if required_tier not in PROXY_POOL_TIER_VALUES:
        raise ValueError(
            f"required_tier must be one of {sorted(PROXY_POOL_TIER_VALUES)}"
        )

    ceiling_index = PROXY_POOL_TIER_ORDER.index(required_tier)
    allowed_tiers = PROXY_POOL_TIER_ORDER[: ceiling_index + 1]

    stmt = (
        select(ProxyPool)
        .options(selectinload(ProxyPool.endpoints))
        .where(
            ProxyPool.enabled.is_(True),
            ProxyPool.tier.in_(allowed_tiers),
            ProxyPool.endpoints.any(ProxyEndpoint.enabled.is_(True)),
        )
    )
    if max_cost is not None:
        stmt = stmt.where(
            (ProxyPool.cost_per_request.is_(None))
            | (ProxyPool.cost_per_request <= max_cost)
        )
    if region_code is not None:
        stmt = stmt.where(
            (ProxyPool.region_code.is_(None)) | (ProxyPool.region_code == region_code)
        )
    if require_sticky:
        stmt = stmt.where(ProxyPool.sticky_session_supported.is_(True))

    candidates = list(session.scalars(stmt).all())
    candidates = [
        pool
        for pool in candidates
        if pool.source_affinity is None or source_code in pool.source_affinity
    ]

    if not candidates:
        raise NoEligibleProxyPoolError()

    candidates.sort(
        key=lambda pool: (
            PROXY_POOL_TIER_ORDER.index(pool.tier),
            _is_degraded(pool),
            pool.priority,
            pool.id,
        )
    )
    return candidates[0]


def _is_degraded(pool: ProxyPool) -> bool:
    rates = [
        endpoint.success_rate_24h
        for endpoint in pool.endpoints
        if endpoint.enabled and endpoint.success_rate_24h is not None
    ]
    if not rates:
        return False

    avg_rate = sum(rates) / len(rates)
    return avg_rate < LOW_SUCCESS_RATE_THRESHOLD


def _select_proxy_endpoint(
    pool_id: int,
    session: Session,
    now: datetime | None,
) -> ProxyEndpoint:
    now_utc = _as_utc_naive(now)
    endpoint = session.scalar(
        select(ProxyEndpoint)
        .where(
            ProxyEndpoint.pool_id == pool_id,
            ProxyEndpoint.enabled.is_(True),
            ProxyEndpoint.current_concurrency < ProxyEndpoint.max_concurrency,
            ProxyEndpoint.ban_score < BAN_SCORE_THRESHOLD,
            (ProxyEndpoint.cooldown_until.is_(None))
            | (ProxyEndpoint.cooldown_until <= now_utc),
        )
        .order_by(
            ProxyEndpoint.success_rate_24h.desc().nulls_last(),
            ProxyEndpoint.current_concurrency.asc(),
            ProxyEndpoint.id.asc(),
        )
        .limit(1)
    )
    if endpoint is None:
        raise NoEligibleProxyEndpointError()
    return endpoint


def _update_proxy_quality_metrics(
    proxy_endpoint_id: int,
    session: Session,
    now: datetime | None,
) -> ProxyEndpoint | None:
    endpoint = session.get(ProxyEndpoint, proxy_endpoint_id)
    if endpoint is None:
        return None

    now_utc = _as_utc_naive(now)
    cutoff_24h = now_utc - timedelta(hours=24)
    cutoff_1h = now_utc - timedelta(hours=1)

    events_24h = list(
        session.scalars(
            select(ProxyHealthEvent).where(
                ProxyHealthEvent.endpoint_id == proxy_endpoint_id,
                ProxyHealthEvent.created_at >= cutoff_24h,
            )
        ).all()
    )
    events_1h = [event for event in events_24h if event.created_at >= cutoff_1h]

    endpoint.success_rate_1h = _success_rate(events_1h)
    endpoint.success_rate_24h = _success_rate(events_24h)
    endpoint.avg_response_ms = _avg_response_ms(events_24h)
    endpoint.ban_score = sum(
        1 for event in events_24h if event.event_type in BAN_EVENT_TYPES
    )
    endpoint.last_403_at = _last_event_at(events_24h, "http_403")
    endpoint.last_429_at = _last_event_at(events_24h, "http_429")
    endpoint.last_captcha_at = _last_event_at(events_24h, "captcha")

    session.commit()
    session.refresh(endpoint)
    return endpoint


def _success_rate(events: list[ProxyHealthEvent]) -> float | None:
    if not events:
        return None
    successes = sum(1 for event in events if event.status == "success")
    return successes / len(events)


def _avg_response_ms(events: list[ProxyHealthEvent]) -> int | None:
    values = [event.response_ms for event in events if event.response_ms is not None]
    if not values:
        return None
    return round(sum(values) / len(values))


def _last_event_at(
    events: list[ProxyHealthEvent],
    event_type: str,
) -> datetime | None:
    timestamps = [
        event.created_at for event in events if event.event_type == event_type
    ]
    if not timestamps:
        return None
    return max(timestamps)


def _as_utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
