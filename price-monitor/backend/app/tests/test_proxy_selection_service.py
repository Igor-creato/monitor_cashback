from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import ProxyEndpoint, ProxyHealthEvent, ProxyPool
from app.services.proxy_selection import (
    NoEligibleProxyEndpointError,
    NoEligibleProxyPoolError,
    select_proxy_endpoint,
    select_proxy_pool,
    update_proxy_quality_metrics,
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

    import app.services.proxy_selection as proxy_selection

    monkeypatch.setattr(proxy_selection, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _add_pool(
    session: Session,
    *,
    source: str = "testshop",
    purpose: str = "price_fetch",
    tier: str = "cheap",
    enabled: bool = True,
    cost_per_request: Decimal | None = None,
    priority: int = 100,
    country_code: str | None = None,
    region_code: str | None = None,
    sticky_session_supported: bool = False,
    source_affinity: list[str] | None = None,
) -> ProxyPool:
    pool = ProxyPool(
        source=source,
        purpose=purpose,
        tier=tier,
        enabled=enabled,
        cost_per_request=cost_per_request,
        priority=priority,
        country_code=country_code,
        region_code=region_code,
        sticky_session_supported=sticky_session_supported,
        source_affinity=source_affinity,
    )
    session.add(pool)
    session.commit()
    session.refresh(pool)
    return pool


def _add_endpoint(
    session: Session,
    pool: ProxyPool,
    *,
    endpoint_ref: str = "proxy-1",
    enabled: bool = True,
    max_concurrency: int = 5,
    current_concurrency: int = 0,
    cooldown_until: datetime | None = None,
    ban_score: int = 0,
    success_rate_24h: float | None = None,
) -> ProxyEndpoint:
    endpoint = ProxyEndpoint(
        pool=pool,
        endpoint_ref=endpoint_ref,
        enabled=enabled,
        max_concurrency=max_concurrency,
        current_concurrency=current_concurrency,
        cooldown_until=cooldown_until,
        ban_score=ban_score,
        success_rate_24h=success_rate_24h,
    )
    session.add(endpoint)
    session.commit()
    session.refresh(endpoint)
    return endpoint


def _add_health_event(
    session: Session,
    endpoint: ProxyEndpoint,
    *,
    event_type: str,
    status: str,
    response_ms: int | None = None,
    created_at: datetime | None = None,
) -> ProxyHealthEvent:
    event = ProxyHealthEvent(
        endpoint=endpoint,
        event_type=event_type,
        status=status,
        response_ms=response_ms,
        created_at=created_at,
    )
    session.add(event)
    session.commit()
    return event


# ── select_proxy_pool ────────────────────────────────────────────────────────


def test_cheap_pool_selected_before_standard(db_session: Session) -> None:
    standard_pool = _add_pool(db_session, source="shop-a", tier="standard")
    cheap_pool = _add_pool(db_session, source="shop-b", tier="cheap")
    _add_endpoint(db_session, standard_pool, endpoint_ref="std-1")
    _add_endpoint(db_session, cheap_pool, endpoint_ref="cheap-1")

    selected = select_proxy_pool(
        "anyshop",
        "standard",
        None,
        session=db_session,
    )

    assert selected.id == cheap_pool.id


def test_free_pool_selected_before_cheap(db_session: Session) -> None:
    cheap_pool = _add_pool(db_session, source="shop-a", tier="cheap")
    free_pool = _add_pool(db_session, source="shop-b", tier="free")
    _add_endpoint(db_session, cheap_pool, endpoint_ref="cheap-1")
    _add_endpoint(db_session, free_pool, endpoint_ref="free-1")

    selected = select_proxy_pool(
        "anyshop",
        "cheap",
        None,
        session=db_session,
    )

    assert selected.id == free_pool.id


def test_premium_pool_not_selected_for_cheap_strategy(db_session: Session) -> None:
    premium_pool = _add_pool(db_session, source="shop-a", tier="premium")
    _add_endpoint(db_session, premium_pool, endpoint_ref="prem-1")

    with pytest.raises(NoEligibleProxyPoolError) as exc_info:
        select_proxy_pool(
            "anyshop",
            "cheap",
            None,
            session=db_session,
        )

    assert exc_info.value.error_type == "no_eligible_pool"


def test_premium_pool_selected_when_strategy_requires_premium(
    db_session: Session,
) -> None:
    premium_pool = _add_pool(db_session, source="shop-a", tier="premium")
    _add_endpoint(db_session, premium_pool, endpoint_ref="prem-1")

    selected = select_proxy_pool(
        "anyshop",
        "premium",
        None,
        session=db_session,
    )

    assert selected.id == premium_pool.id


def test_max_cost_excludes_expensive_pool(db_session: Session) -> None:
    expensive_pool = _add_pool(
        db_session,
        source="shop-a",
        tier="cheap",
        cost_per_request=Decimal("0.05000000"),
    )
    _add_endpoint(db_session, expensive_pool, endpoint_ref="exp-1")

    with pytest.raises(NoEligibleProxyPoolError):
        select_proxy_pool(
            "anyshop",
            "cheap",
            Decimal("0.01"),
            session=db_session,
        )


def test_max_cost_allows_affordable_pool(db_session: Session) -> None:
    expensive_pool = _add_pool(
        db_session,
        source="shop-a",
        tier="cheap",
        cost_per_request=Decimal("0.05000000"),
    )
    affordable_pool = _add_pool(
        db_session,
        source="shop-b",
        tier="standard",
        cost_per_request=Decimal("0.00500000"),
    )
    _add_endpoint(db_session, expensive_pool, endpoint_ref="exp-1")
    _add_endpoint(db_session, affordable_pool, endpoint_ref="aff-1")

    selected = select_proxy_pool(
        "anyshop",
        "standard",
        Decimal("0.01"),
        session=db_session,
    )

    assert selected.id == affordable_pool.id


def test_disabled_pool_is_not_selected(db_session: Session) -> None:
    disabled_pool = _add_pool(db_session, source="shop-a", tier="cheap", enabled=False)
    _add_endpoint(db_session, disabled_pool, endpoint_ref="dis-1")

    with pytest.raises(NoEligibleProxyPoolError):
        select_proxy_pool(
            "anyshop",
            "cheap",
            None,
            session=db_session,
        )


def test_region_code_filters_pools(db_session: Session) -> None:
    foreign_pool = _add_pool(
        db_session,
        source="shop-a",
        tier="cheap",
        region_code="eu",
    )
    matching_pool = _add_pool(
        db_session,
        source="shop-b",
        tier="standard",
        region_code="ru",
    )
    _add_endpoint(db_session, foreign_pool, endpoint_ref="eu-1")
    _add_endpoint(db_session, matching_pool, endpoint_ref="ru-1")

    selected = select_proxy_pool(
        "anyshop",
        "standard",
        None,
        region_code="ru",
        session=db_session,
    )

    assert selected.id == matching_pool.id


def test_low_pool_success_rate_lowers_priority(db_session: Session) -> None:
    bad_pool = _add_pool(db_session, source="shop-a", tier="cheap", priority=10)
    good_pool = _add_pool(db_session, source="shop-b", tier="cheap", priority=100)
    _add_endpoint(db_session, bad_pool, endpoint_ref="bad-1", success_rate_24h=0.2)
    _add_endpoint(db_session, good_pool, endpoint_ref="good-1", success_rate_24h=0.9)

    selected = select_proxy_pool(
        "anyshop",
        "cheap",
        None,
        session=db_session,
    )

    assert selected.id == good_pool.id


def test_sticky_session_required_excludes_non_sticky_pools(
    db_session: Session,
) -> None:
    non_sticky_pool = _add_pool(
        db_session,
        source="shop-a",
        tier="cheap",
        sticky_session_supported=False,
    )
    sticky_pool = _add_pool(
        db_session,
        source="shop-b",
        tier="standard",
        sticky_session_supported=True,
    )
    _add_endpoint(db_session, non_sticky_pool, endpoint_ref="ns-1")
    _add_endpoint(db_session, sticky_pool, endpoint_ref="st-1")

    selected = select_proxy_pool(
        "anyshop",
        "standard",
        None,
        require_sticky=True,
        session=db_session,
    )

    assert selected.id == sticky_pool.id


def test_source_affinity_filters_pools(db_session: Session) -> None:
    other_pool = _add_pool(
        db_session,
        source="shop-a",
        tier="cheap",
        source_affinity=["othershop"],
    )
    matching_pool = _add_pool(
        db_session,
        source="shop-b",
        tier="standard",
        source_affinity=["targetshop"],
    )
    _add_endpoint(db_session, other_pool, endpoint_ref="o-1")
    _add_endpoint(db_session, matching_pool, endpoint_ref="m-1")

    selected = select_proxy_pool(
        "targetshop",
        "standard",
        None,
        session=db_session,
    )

    assert selected.id == matching_pool.id


def test_no_pools_raises_typed_error(db_session: Session) -> None:
    with pytest.raises(NoEligibleProxyPoolError) as exc_info:
        select_proxy_pool(
            "anyshop",
            "premium",
            None,
            session=db_session,
        )

    assert exc_info.value.error_type == "no_eligible_pool"


# ── select_proxy_endpoint ────────────────────────────────────────────────────


def test_endpoint_with_high_ban_score_is_not_selected(db_session: Session) -> None:
    pool = _add_pool(db_session, tier="cheap")
    _add_endpoint(db_session, pool, endpoint_ref="banned-1", ban_score=100)

    with pytest.raises(NoEligibleProxyEndpointError) as exc_info:
        select_proxy_endpoint(pool.id, session=db_session)

    assert exc_info.value.error_type == "no_eligible_endpoint"


def test_endpoint_in_cooldown_is_not_selected(db_session: Session) -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    pool = _add_pool(db_session, tier="cheap")
    _add_endpoint(
        db_session,
        pool,
        endpoint_ref="cool-1",
        cooldown_until=(now + timedelta(minutes=5)).replace(tzinfo=None),
    )

    with pytest.raises(NoEligibleProxyEndpointError):
        select_proxy_endpoint(pool.id, session=db_session, now=now)


def test_endpoint_after_cooldown_is_selected(db_session: Session) -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    pool = _add_pool(db_session, tier="cheap")
    endpoint = _add_endpoint(
        db_session,
        pool,
        endpoint_ref="cooled-1",
        cooldown_until=(now - timedelta(minutes=5)).replace(tzinfo=None),
    )

    selected = select_proxy_endpoint(pool.id, session=db_session, now=now)

    assert selected.id == endpoint.id


def test_success_rate_affects_endpoint_selection(db_session: Session) -> None:
    pool = _add_pool(db_session, tier="cheap")
    _add_endpoint(
        db_session,
        pool,
        endpoint_ref="bad-1",
        success_rate_24h=0.3,
    )
    good_endpoint = _add_endpoint(
        db_session,
        pool,
        endpoint_ref="good-1",
        success_rate_24h=0.95,
    )

    selected = select_proxy_endpoint(pool.id, session=db_session)

    assert selected.id == good_endpoint.id


def test_endpoint_at_max_concurrency_is_not_selected(db_session: Session) -> None:
    pool = _add_pool(db_session, tier="cheap")
    _add_endpoint(
        db_session,
        pool,
        endpoint_ref="busy-1",
        max_concurrency=2,
        current_concurrency=2,
    )

    with pytest.raises(NoEligibleProxyEndpointError):
        select_proxy_endpoint(pool.id, session=db_session)


def test_empty_pool_raises_typed_error(db_session: Session) -> None:
    pool = _add_pool(db_session, tier="cheap")

    with pytest.raises(NoEligibleProxyEndpointError) as exc_info:
        select_proxy_endpoint(pool.id, session=db_session)

    assert exc_info.value.error_type == "no_eligible_endpoint"


# ── update_proxy_quality_metrics ─────────────────────────────────────────────


def test_quality_metrics_are_calculated_from_health_events(
    db_session: Session,
) -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    pool = _add_pool(db_session, tier="cheap")
    endpoint = _add_endpoint(db_session, pool, endpoint_ref="metrics-1")

    # 8 успехов 30 минут назад (входят в окна 1h и 24h)
    for _ in range(8):
        _add_health_event(
            db_session,
            endpoint,
            event_type="success",
            status="success",
            response_ms=100,
            created_at=(now - timedelta(minutes=30)).replace(tzinfo=None),
        )
    # 2 бан-события 2 часа назад (входят только в окно 24h)
    for _ in range(2):
        _add_health_event(
            db_session,
            endpoint,
            event_type="http_429",
            status="failed",
            response_ms=300,
            created_at=(now - timedelta(hours=2)).replace(tzinfo=None),
        )
    # событие за пределами 24h — игнорируется
    _add_health_event(
        db_session,
        endpoint,
        event_type="http_403",
        status="failed",
        created_at=(now - timedelta(hours=30)).replace(tzinfo=None),
    )

    update_proxy_quality_metrics(endpoint.id, session=db_session, now=now)

    db_session.refresh(endpoint)
    assert endpoint.success_rate_1h == pytest.approx(1.0)
    assert endpoint.success_rate_24h == pytest.approx(0.8)
    assert endpoint.avg_response_ms == 140  # (8*100 + 2*300) / 10
    assert endpoint.ban_score == 2
    assert endpoint.last_429_at == (now - timedelta(hours=2)).replace(tzinfo=None)
    assert endpoint.last_403_at is None
    assert endpoint.last_captcha_at is None


def test_quality_metrics_with_no_events_reset_to_none(db_session: Session) -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    pool = _add_pool(db_session, tier="cheap")
    endpoint = _add_endpoint(
        db_session,
        pool,
        endpoint_ref="empty-1",
        ban_score=10,
        success_rate_24h=0.5,
    )

    update_proxy_quality_metrics(endpoint.id, session=db_session, now=now)

    db_session.refresh(endpoint)
    assert endpoint.success_rate_1h is None
    assert endpoint.success_rate_24h is None
    assert endpoint.avg_response_ms is None
    assert endpoint.ban_score == 0
