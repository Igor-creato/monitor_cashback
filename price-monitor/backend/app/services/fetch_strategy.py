from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import SourceHealthEvent
from app.services.source_profiles import SourceProfile, get_source_profile
from app.services.user_limits import UserPriceMonitorLimits

RECENT_DEGRADATION_WINDOW = timedelta(minutes=30)
DEGRADATION_EVENTS = frozenset({"http_403", "http_429"})


@dataclass(frozen=True)
class FetchStrategyDecision:
    strategy: str
    reason: str
    proxy_required: bool
    proxy_tier: str | None
    browser_required: bool
    max_attempts: int
    timeout_seconds: int
    cost_level: str
    allow_fallback: bool


def select_fetch_strategy(
    source_code: str,
    *,
    session: Session | None = None,
    user_limits: UserPriceMonitorLimits | None = None,
    has_fresh_feed_data: bool = False,
    cost_budget_exceeded: bool = False,
    now: datetime | None = None,
) -> FetchStrategyDecision:
    if has_fresh_feed_data:
        return _decision(
            strategy="feed",
            reason="fresh_feed_data",
            cost_level="free",
            max_attempts=1,
        )

    if cost_budget_exceeded:
        return _quarantine("cost_budget_exceeded")

    if session is not None:
        return _select_with_session(
            source_code,
            session,
            user_limits=user_limits,
            now=now,
        )

    if SessionLocal is None:
        profile = get_source_profile(source_code)
        return _select_from_profile(
            profile,
            recent_degradation_event=None,
            user_limits=user_limits,
        )

    with SessionLocal() as owned_session:
        return _select_with_session(
            source_code,
            owned_session,
            user_limits=user_limits,
            now=now,
        )


def _select_with_session(
    source_code: str,
    session: Session,
    *,
    user_limits: UserPriceMonitorLimits | None,
    now: datetime | None,
) -> FetchStrategyDecision:
    profile = get_source_profile(source_code, session=session)
    recent_degradation_event = _recent_degradation_event(
        source_code,
        session,
        now or datetime.now(UTC),
    )
    return _select_from_profile(
        profile,
        recent_degradation_event=recent_degradation_event,
        user_limits=user_limits,
    )


def _select_from_profile(
    profile: SourceProfile,
    *,
    recent_degradation_event: str | None,
    user_limits: UserPriceMonitorLimits | None,
) -> FetchStrategyDecision:
    if not profile.enabled:
        return _quarantine("source_disabled_or_quarantined")

    browser_fallback_allowed = _browser_fallback_allowed(user_limits)

    if profile.difficulty_class == "light":
        if recent_degradation_event is not None:
            return _decision(
                strategy="cheap_proxy_http",
                reason=f"recent_degradation_{recent_degradation_event}",
                proxy_required=True,
                proxy_tier="cheap",
                cost_level="cheap",
                timeout_seconds=15,
            )

        return _decision(
            strategy=_light_http_strategy(profile),
            reason="light_source_healthy",
            cost_level="free",
            timeout_seconds=10,
        )

    if profile.difficulty_class == "medium":
        if browser_fallback_allowed:
            reason = "medium_source_standard_proxy_first_fallback_crawl4ai_browser"
        else:
            reason = "medium_source_standard_proxy_first_browser_fallback_not_allowed"
        return _decision(
            strategy="standard_proxy_http",
            reason=reason,
            proxy_required=True,
            proxy_tier="standard",
            cost_level="standard",
            timeout_seconds=25,
            allow_fallback=browser_fallback_allowed,
        )

    if profile.difficulty_class == "heavy":
        if browser_fallback_allowed:
            reason = "heavy_source_residential_proxy_first_fallback_camoufox_browser"
        else:
            reason = "heavy_source_residential_proxy_first_browser_fallback_not_allowed"
        return _decision(
            strategy="residential_proxy_http",
            reason=reason,
            proxy_required=True,
            proxy_tier="residential",
            cost_level="expensive",
            timeout_seconds=45,
            allow_fallback=browser_fallback_allowed,
        )

    return _quarantine("unsupported_source_difficulty")


def _recent_degradation_event(
    source_code: str,
    session: Session,
    now: datetime,
) -> str | None:
    cutoff = _as_utc_naive(now - RECENT_DEGRADATION_WINDOW)
    return session.scalar(
        select(SourceHealthEvent.event_type)
        .where(
            SourceHealthEvent.source_code == source_code,
            SourceHealthEvent.event_type.in_(DEGRADATION_EVENTS),
            SourceHealthEvent.created_at >= cutoff,
        )
        .order_by(SourceHealthEvent.created_at.desc(), SourceHealthEvent.id.desc())
        .limit(1)
    )


def _light_http_strategy(profile: SourceProfile) -> str:
    if profile.preferred_transport == "curl_cffi":
        return "curl_cffi_http"
    return "direct_http"


def _browser_fallback_allowed(user_limits: UserPriceMonitorLimits | None) -> bool:
    if user_limits is None:
        return False
    return user_limits.limits.browser_fallback_allowed


def _quarantine(reason: str) -> FetchStrategyDecision:
    return _decision(
        strategy="quarantine",
        reason=reason,
        cost_level="blocked",
        max_attempts=0,
        timeout_seconds=0,
    )


def _decision(
    *,
    strategy: str,
    reason: str,
    cost_level: str,
    proxy_required: bool = False,
    proxy_tier: str | None = None,
    browser_required: bool = False,
    max_attempts: int = 2,
    timeout_seconds: int = 10,
    allow_fallback: bool = False,
) -> FetchStrategyDecision:
    return FetchStrategyDecision(
        strategy=strategy,
        reason=reason,
        proxy_required=proxy_required,
        proxy_tier=proxy_tier,
        browser_required=browser_required,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        cost_level=cost_level,
        allow_fallback=allow_fallback,
    )


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
