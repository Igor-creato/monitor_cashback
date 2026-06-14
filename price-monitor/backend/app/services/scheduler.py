from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
from app.models.monitoring import (
    FetchJob,
    SourceConfig,
    SourceHealthEvent,
    TrackedProduct,
    UserProductSubscription,
)
from app.services.fetch_jobs import FETCH_JOB_ACTIVE_STATUSES
from app.services.fetch_strategy import select_fetch_strategy
from app.services.source_quarantine import get_effective_source_quarantine_state
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserLimitsNotFound,
    UserPriceMonitorLimits,
    get_price_monitor_limits,
)

DEFAULT_SOURCE_INTERVAL = timedelta(minutes=60)
FREE_FALLBACK_INTERVAL_MINUTES = 360
BAD_SOURCE_HEALTH_WINDOW = timedelta(minutes=30)
STALE_INTEREST_WINDOW = timedelta(days=30)
BAD_SOURCE_HEALTH_EVENTS = frozenset(
    {"timeout", "http_403", "http_429", "captcha_detected"}
)
COST_UNITS_BY_LEVEL = {
    "free": 0,
    "cheap": 1,
    "standard": 3,
    "expensive": 10,
}


LimitsProvider = Callable[[str, str], UserPriceMonitorLimits | UserLimitsNotFound]


@dataclass(frozen=True)
class SchedulerCostBudget:
    max_cost_units: int = 30


@dataclass(frozen=True)
class ScheduledJobReport:
    tracked_product_id: int
    fetch_job_id: int
    priority: int
    reason: str
    cost_level: str
    cost_units: int


@dataclass(frozen=True)
class SkippedScheduleItem:
    tracked_product_id: int
    reason: str


@dataclass(frozen=True)
class ScheduleDueFetchReport:
    scheduled: list[ScheduledJobReport] = field(default_factory=list)
    skipped: list[SkippedScheduleItem] = field(default_factory=list)
    cost_units_used: int = 0

    @property
    def scheduled_count(self) -> int:
        return len(self.scheduled)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass(frozen=True)
class DueProductCandidate:
    tracked_product: TrackedProduct
    priority: int
    subscriber_limits: list[UserPriceMonitorLimits]
    best_user_limits: UserPriceMonitorLimits
    has_non_free_subscriber: bool
    source_health_penalty: int
    stale_interest_penalty: int
    due_interval: timedelta


@dataclass(frozen=True)
class _CollectedProducts:
    candidates: list[DueProductCandidate]
    skipped: list[SkippedScheduleItem]


def select_products_due_for_check(
    limit,
    *,
    session: Session | None = None,
    now: datetime | None = None,
    limits_provider: LimitsProvider = get_price_monitor_limits,
    cost_budget: SchedulerCostBudget | None = None,
) -> list[DueProductCandidate]:
    del cost_budget
    now_utc = _as_utc(now or datetime.now(UTC))

    if session is not None:
        return _collect_products_due_for_check(
            limit,
            session,
            now=now_utc,
            limits_provider=limits_provider,
        ).candidates

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _collect_products_due_for_check(
            limit,
            owned_session,
            now=now_utc,
            limits_provider=limits_provider,
        ).candidates


def calculate_product_priority(
    tracked_product,
    *,
    now: datetime | None = None,
    subscriber_limits: list[UserPriceMonitorLimits] | None = None,
    source_health_penalty=0,
) -> int:
    now_utc = _as_utc(now or datetime.now(UTC))
    active_subscriptions = [
        subscription
        for subscription in tracked_product.subscriptions
        if subscription.is_active is True
    ]

    priority = 1000
    priority += min(len(active_subscriptions), 100) * 10
    priority += _target_proximity_bonus(tracked_product, active_subscriptions)

    if _has_non_free_subscriber(subscriber_limits or []):
        priority += 200

    if tracked_product.last_checked_at is not None:
        overdue_minutes = max(
            0,
            int(
                (now_utc - _as_utc(tracked_product.last_checked_at)).total_seconds()
                // 60
            ),
        )
        priority += min(overdue_minutes // 10, 300)

    priority -= int(source_health_penalty)

    if _interest_is_stale(tracked_product, active_subscriptions, now_utc):
        priority -= 200

    return max(1, min(9999, int(priority)))


def schedule_due_fetch_jobs(
    limit,
    *,
    session: Session | None = None,
    now: datetime | None = None,
    limits_provider: LimitsProvider = get_price_monitor_limits,
    cost_budget: SchedulerCostBudget | None = None,
) -> ScheduleDueFetchReport:
    now_utc = _as_utc(now or datetime.now(UTC))
    active_budget = cost_budget or SchedulerCostBudget()

    if session is not None:
        return _schedule_due_fetch_jobs(
            limit,
            session,
            now=now_utc,
            limits_provider=limits_provider,
            cost_budget=active_budget,
        )

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _schedule_due_fetch_jobs(
            limit,
            owned_session,
            now=now_utc,
            limits_provider=limits_provider,
            cost_budget=active_budget,
        )


def _schedule_due_fetch_jobs(
    limit: int,
    session: Session,
    *,
    now: datetime,
    limits_provider: LimitsProvider,
    cost_budget: SchedulerCostBudget,
) -> ScheduleDueFetchReport:
    collected = _collect_products_due_for_check(
        None,
        session,
        now=now,
        limits_provider=limits_provider,
    )
    scheduled: list[ScheduledJobReport] = []
    skipped = list(collected.skipped)
    cost_units_used = 0

    for candidate in collected.candidates:
        if len(scheduled) >= int(limit):
            break

        cost_reason = _cost_skip_reason(
            candidate,
            session,
            now=now,
            budget=cost_budget,
            cost_units_used=cost_units_used,
        )
        if cost_reason is not None:
            skipped.append(
                SkippedScheduleItem(
                    tracked_product_id=candidate.tracked_product.id,
                    reason=cost_reason,
                )
            )
            continue

        cost_level = _strategy_cost_level(candidate, session, now=now)
        cost_units = COST_UNITS_BY_LEVEL.get(cost_level, 0)
        job = FetchJob(
            tracked_product_id=candidate.tracked_product.id,
            priority=candidate.priority,
            status="queued",
            reason="scheduled",
            next_run_at=now.replace(tzinfo=None),
        )
        session.add(job)
        session.flush()
        scheduled.append(
            ScheduledJobReport(
                tracked_product_id=candidate.tracked_product.id,
                fetch_job_id=job.id,
                priority=candidate.priority,
                reason="scheduled",
                cost_level=cost_level,
                cost_units=cost_units,
            )
        )
        cost_units_used += cost_units

    session.commit()
    return ScheduleDueFetchReport(
        scheduled=scheduled,
        skipped=skipped,
        cost_units_used=cost_units_used,
    )


def _collect_products_due_for_check(
    limit: int | None,
    session: Session,
    *,
    now: datetime,
    limits_provider: LimitsProvider,
) -> _CollectedProducts:
    candidates: list[DueProductCandidate] = []
    skipped: list[SkippedScheduleItem] = []

    for tracked_product in _active_tracked_products(session):
        product_skipped = _product_skip_reason(tracked_product, session, now=now)
        if product_skipped is not None:
            skipped.append(
                SkippedScheduleItem(
                    tracked_product_id=tracked_product.id,
                    reason=product_skipped,
                )
            )
            continue

        active_subscriptions = [
            subscription
            for subscription in tracked_product.subscriptions
            if subscription.is_active is True
        ]
        subscriber_limits = [
            _safe_limits(subscription, limits_provider)
            for subscription in active_subscriptions
        ]
        if not subscriber_limits:
            continue

        source_health_penalty = _source_health_penalty(
            tracked_product.source,
            session,
            now=now,
        )
        interval = _due_interval(
            tracked_product,
            active_subscriptions,
            subscriber_limits,
            session,
            source_health_penalty=source_health_penalty,
            now=now,
        )
        if _is_fresh(tracked_product.last_checked_at, now, interval):
            skipped.append(
                SkippedScheduleItem(
                    tracked_product_id=tracked_product.id,
                    reason="fresh",
                )
            )
            continue

        stale_interest_penalty = (
            200
            if _interest_is_stale(
                tracked_product,
                active_subscriptions,
                now,
            )
            else 0
        )
        priority = calculate_product_priority(
            tracked_product,
            now=now,
            subscriber_limits=subscriber_limits,
            source_health_penalty=source_health_penalty,
        )
        candidates.append(
            DueProductCandidate(
                tracked_product=tracked_product,
                priority=priority,
                subscriber_limits=subscriber_limits,
                best_user_limits=_best_user_limits(subscriber_limits),
                has_non_free_subscriber=_has_non_free_subscriber(subscriber_limits),
                source_health_penalty=source_health_penalty,
                stale_interest_penalty=stale_interest_penalty,
                due_interval=interval,
            )
        )

    candidates.sort(
        key=lambda candidate: (-candidate.priority, candidate.tracked_product.id)
    )
    if limit is not None:
        candidates = candidates[: int(limit)]
    return _CollectedProducts(candidates=candidates, skipped=skipped)


def _active_tracked_products(session: Session) -> list[TrackedProduct]:
    return list(
        session.scalars(
            select(TrackedProduct)
            .join(UserProductSubscription)
            .options(selectinload(TrackedProduct.subscriptions))
            .where(UserProductSubscription.is_active.is_(True))
            .distinct()
        ).all()
    )


def _product_skip_reason(
    tracked_product: TrackedProduct,
    session: Session,
    *,
    now: datetime,
) -> str | None:
    if _has_active_fetch_job(tracked_product.id, session):
        return "active_job_exists"

    quarantine_state = get_effective_source_quarantine_state(
        tracked_product.source,
        session=session,
        now=now,
    )
    if quarantine_state.is_blocked:
        return f"source_{quarantine_state.status}"

    return None


def _has_active_fetch_job(tracked_product_id: int, session: Session) -> bool:
    return (
        session.scalar(
            select(FetchJob.id)
            .where(
                FetchJob.tracked_product_id == tracked_product_id,
                FetchJob.status.in_(FETCH_JOB_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        is not None
    )


def _safe_limits(
    subscription: UserProductSubscription,
    limits_provider: LimitsProvider,
) -> UserPriceMonitorLimits:
    try:
        limits = limits_provider(subscription.site_id, subscription.external_user_id)
    except Exception:
        return _free_fallback_limits(subscription.external_user_id)

    if isinstance(limits, UserLimitsNotFound):
        return _free_fallback_limits(subscription.external_user_id)
    return limits


def _free_fallback_limits(external_user_id: str) -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id=external_user_id,
        tariff="free",
        limits=PriceMonitorLimitValues(
            max_tracked_products=0,
            history_days=30,
            min_fetch_interval_minutes=FREE_FALLBACK_INTERVAL_MINUTES,
            alerts_per_day=0,
            manual_refresh_per_day=0,
            browser_fallback_allowed=False,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0"),
            cashback_currency="RUB",
        ),
    )


def _due_interval(
    tracked_product: TrackedProduct,
    active_subscriptions: list[UserProductSubscription],
    subscriber_limits: list[UserPriceMonitorLimits],
    session: Session,
    *,
    source_health_penalty: int,
    now: datetime,
) -> timedelta:
    source_interval = _source_min_interval(tracked_product.source, session)
    subscriber_interval = timedelta(
        minutes=min(
            limits.limits.min_fetch_interval_minutes for limits in subscriber_limits
        )
    )
    interval = max(source_interval, subscriber_interval)

    if source_health_penalty > 0:
        interval *= 2

    if _interest_is_stale(tracked_product, active_subscriptions, now):
        interval *= 2

    return interval


def _source_min_interval(source_code: str, session: Session) -> timedelta:
    minutes = session.scalar(
        select(SourceConfig.min_fetch_interval_minutes)
        .where(SourceConfig.source_code == source_code)
        .limit(1)
    )
    if minutes is None:
        return DEFAULT_SOURCE_INTERVAL
    return timedelta(minutes=minutes)


def _source_health_penalty(
    source_code: str,
    session: Session,
    *,
    now: datetime,
) -> int:
    cutoff = (now - BAD_SOURCE_HEALTH_WINDOW).replace(tzinfo=None)
    has_recent_bad_health = (
        session.scalar(
            select(SourceHealthEvent.id)
            .where(
                SourceHealthEvent.source_code == source_code,
                SourceHealthEvent.event_type.in_(BAD_SOURCE_HEALTH_EVENTS),
                SourceHealthEvent.created_at >= cutoff,
            )
            .limit(1)
        )
        is not None
    )
    return 200 if has_recent_bad_health else 0


def _is_fresh(
    last_checked_at: datetime | None,
    now: datetime,
    interval: timedelta,
) -> bool:
    if last_checked_at is None:
        return False
    return _as_utc(last_checked_at) > now - interval


def _interest_is_stale(
    tracked_product: TrackedProduct,
    active_subscriptions: list[UserProductSubscription],
    now: datetime,
) -> bool:
    newest_interest = tracked_product.updated_at
    for subscription in active_subscriptions:
        if newest_interest is None or subscription.updated_at > newest_interest:
            newest_interest = subscription.updated_at

    if newest_interest is None:
        return False
    return _as_utc(newest_interest) < now - STALE_INTEREST_WINDOW


def _target_proximity_bonus(
    tracked_product: TrackedProduct,
    active_subscriptions: list[UserProductSubscription],
) -> int:
    if tracked_product.last_price is None:
        return 0

    bonuses: list[int] = []
    current_price = Decimal(tracked_product.last_price)
    for subscription in active_subscriptions:
        if subscription.target_price is None or subscription.target_price <= 0:
            continue
        target_price = Decimal(subscription.target_price)
        if current_price <= target_price:
            bonuses.append(700)
            continue
        distance_ratio = (current_price - target_price) / target_price
        if distance_ratio <= Decimal("0.10"):
            bonuses.append(500)
        elif distance_ratio <= Decimal("0.25"):
            bonuses.append(250)

    return max(bonuses, default=0)


def _has_non_free_subscriber(subscriber_limits: list[UserPriceMonitorLimits]) -> bool:
    return any(limits.tariff.lower() != "free" for limits in subscriber_limits)


def _best_user_limits(
    subscriber_limits: list[UserPriceMonitorLimits],
) -> UserPriceMonitorLimits:
    return sorted(
        subscriber_limits,
        key=lambda limits: (
            limits.tariff.lower() == "free",
            limits.limits.min_fetch_interval_minutes,
        ),
    )[0]


def _cost_skip_reason(
    candidate: DueProductCandidate,
    session: Session,
    *,
    now: datetime,
    budget: SchedulerCostBudget,
    cost_units_used: int,
) -> str | None:
    cost_level = _strategy_cost_level(candidate, session, now=now)
    if cost_level == "blocked":
        return "strategy_blocked"

    cost_units = COST_UNITS_BY_LEVEL.get(cost_level, 0)
    if cost_level == "expensive" and candidate.has_non_free_subscriber is False:
        return "free_only_expensive_strategy_not_allowed"

    if cost_units_used + cost_units > budget.max_cost_units:
        return "cost_budget_exceeded"

    return None


def _strategy_cost_level(
    candidate: DueProductCandidate,
    session: Session,
    *,
    now: datetime,
) -> str:
    decision = select_fetch_strategy(
        candidate.tracked_product.source,
        session=session,
        user_limits=candidate.best_user_limits,
        cost_budget_exceeded=False,
        now=now,
    )
    return decision.cost_level


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
