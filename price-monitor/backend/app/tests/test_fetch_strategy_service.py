from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import (
    SourceFetchProfile,
    SourceHealthEvent,
    SourceQuarantineState,
)
from app.services.fetch_strategy import select_fetch_strategy
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserPriceMonitorLimits,
)

NOW = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.fetch_strategy as fetch_strategy
    import app.services.source_profiles as source_profiles

    monkeypatch.setattr(fetch_strategy, "SessionLocal", session_factory)
    monkeypatch.setattr(source_profiles, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _user_limits(
    *, tariff: str, browser_fallback_allowed: bool
) -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id="77",
        tariff=tariff,
        limits=PriceMonitorLimitValues(
            max_tracked_products=10,
            history_days=30,
            min_fetch_interval_minutes=60,
            alerts_per_day=10,
            manual_refresh_per_day=5,
            browser_fallback_allowed=browser_fallback_allowed,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0.5"),
            cashback_currency="RUB",
        ),
    )


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


def test_light_healthy_source_uses_curl_cffi_or_direct_http(
    db_session: Session,
) -> None:
    decision = select_fetch_strategy("testshop", session=db_session, now=NOW)

    assert decision.strategy in {"curl_cffi_http", "direct_http"}
    assert decision.strategy == "curl_cffi_http"
    assert decision.proxy_required is False
    assert decision.browser_required is False
    assert decision.cost_level == "free"
    assert decision.max_attempts == 2


def test_light_source_after_recent_429_uses_cheap_proxy(db_session: Session) -> None:
    _record_health(db_session, "testshop", "http_429", NOW - timedelta(minutes=5))

    decision = select_fetch_strategy("testshop", session=db_session, now=NOW)

    assert decision.strategy == "cheap_proxy_http"
    assert decision.proxy_required is True
    assert decision.proxy_tier == "cheap"
    assert decision.browser_required is False
    assert decision.cost_level == "cheap"
    assert decision.max_attempts == 2
    assert "http_429" in decision.reason


def test_medium_source_uses_standard_proxy_first(db_session: Session) -> None:
    decision = select_fetch_strategy("example_market", session=db_session, now=NOW)

    assert decision.strategy == "standard_proxy_http"
    assert decision.proxy_required is True
    assert decision.proxy_tier == "standard"
    assert decision.browser_required is False
    assert decision.cost_level == "standard"
    assert decision.allow_fallback is False


def test_heavy_source_uses_residential_proxy_with_browser_fallback_when_allowed(
    db_session: Session,
) -> None:
    decision = select_fetch_strategy(
        "ozon",
        session=db_session,
        user_limits=_user_limits(tariff="pro", browser_fallback_allowed=True),
        now=NOW,
    )

    assert decision.strategy == "residential_proxy_http"
    assert decision.proxy_required is True
    assert decision.proxy_tier == "residential"
    assert decision.browser_required is False
    assert decision.cost_level == "expensive"
    assert decision.allow_fallback is True
    assert "camoufox_browser" in decision.reason


def test_quarantined_source_returns_quarantine(db_session: Session) -> None:
    db_session.add(
        SourceFetchProfile(
            source_code="testshop",
            difficulty_class="light",
            preferred_transport="curl_cffi",
            fallback_transports=["direct_http"],
            proxy_tier_policy="cheap_first",
            browser_required=False,
            extraction_mode="json",
            image_policy="copy_to_object_storage",
            enabled=False,
        )
    )
    db_session.commit()

    decision = select_fetch_strategy("testshop", session=db_session, now=NOW)

    assert decision.strategy == "quarantine"
    assert decision.cost_level == "blocked"
    assert decision.max_attempts == 0
    assert decision.allow_fallback is False
    assert "disabled" in decision.reason


def test_source_quarantine_state_blocks_fetch_strategy(db_session: Session) -> None:
    db_session.add(
        SourceQuarantineState(
            source_code="testshop",
            status="quarantined",
            reason="too_many_403",
            error_type="http_403",
            quarantined_until=(NOW + timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    db_session.commit()

    decision = select_fetch_strategy("testshop", session=db_session, now=NOW)

    assert decision.strategy == "quarantine"
    assert decision.cost_level == "blocked"
    assert decision.max_attempts == 0
    assert decision.reason == "source_quarantined_too_many_403"


def test_free_limits_do_not_receive_expensive_browser_strategy(
    db_session: Session,
) -> None:
    decision = select_fetch_strategy(
        "example_market",
        session=db_session,
        user_limits=_user_limits(tariff="free", browser_fallback_allowed=False),
        now=NOW,
    )

    assert decision.strategy == "standard_proxy_http"
    assert decision.browser_required is False
    assert decision.cost_level == "standard"
    assert decision.allow_fallback is False
    assert "browser_fallback_not_allowed" in decision.reason


def test_pro_limits_allow_browser_fallback(db_session: Session) -> None:
    decision = select_fetch_strategy(
        "example_market",
        session=db_session,
        user_limits=_user_limits(tariff="pro", browser_fallback_allowed=True),
        now=NOW,
    )

    assert decision.strategy == "standard_proxy_http"
    assert decision.browser_required is False
    assert decision.cost_level == "standard"
    assert decision.allow_fallback is True
    assert "crawl4ai_browser" in decision.reason


def test_cost_budget_exceeded_returns_blocked_quarantine(db_session: Session) -> None:
    decision = select_fetch_strategy(
        "testshop",
        session=db_session,
        cost_budget_exceeded=True,
        now=NOW,
    )

    assert decision.strategy == "quarantine"
    assert decision.cost_level == "blocked"
    assert decision.max_attempts == 0
    assert decision.reason == "cost_budget_exceeded"


def test_decision_always_contains_reason(db_session: Session) -> None:
    decisions = [
        select_fetch_strategy("testshop", session=db_session, now=NOW),
        select_fetch_strategy(
            "testshop",
            session=db_session,
            has_fresh_feed_data=True,
            now=NOW,
        ),
        select_fetch_strategy("unknown_source", session=db_session, now=NOW),
    ]

    assert all(decision.reason for decision in decisions)
