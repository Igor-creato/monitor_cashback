from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, case, func, literal, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.monitoring import (
    FetchAttempt,
    FetchJob,
    MetricCounter,
    NotificationEvent,
    ProxyPool,
    SourceHealthEvent,
    SourceQuarantineState,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

CHART_REQUESTS_METRIC = "price_monitor_chart_requests_total"
BROWSER_FALLBACK_STRATEGIES = frozenset(
    {"crawl4ai", "crawl4ai_browser", "playwright", "camoufox", "camoufox_browser"}
)
EXTRACTION_ERROR_TYPES = frozenset({"parser_error", "price_not_found"})


def render_prometheus_metrics(session: Session) -> str:
    lines = [
        f"price_monitor_products_total {_count(session, TrackedProduct.id)}",
        "price_monitor_active_subscriptions_total "
        f"{_count_active_subscriptions(session)}",
    ]
    lines.extend(
        _sample(
            "price_monitor_fetch_jobs_total",
            {"status": status},
            count,
        )
        for status, count in _group_counts(session, FetchJob.status)
    )
    lines.extend(
        _sample(
            "price_monitor_cashback_status_total",
            {"cashback_status": cashback_status},
            count,
        )
        for cashback_status, count in _group_counts(
            session,
            TrackedProductCashback.cashback_status,
        )
    )
    lines.extend(
        _sample(
            "price_monitor_notification_events_total",
            {"status": status, "event_type": event_type},
            count,
        )
        for status, event_type, count in _notification_counts(session)
    )
    lines.extend(
        _sample(
            "price_monitor_source_events_total",
            {"source": source, "event_type": event_type},
            count,
        )
        for source, event_type, count in _source_event_counts(session)
    )
    lines.extend(
        _sample(
            "price_monitor_fetch_attempts_total",
            {
                "source": source,
                "strategy": strategy,
                "status": status,
                "error_type": error_type,
            },
            count,
        )
        for source, strategy, status, error_type, count in _fetch_attempt_counts(
            session
        )
    )
    lines.extend(
        _sample(
            "price_monitor_fetch_cost_estimated_total",
            {"source": source, "strategy": strategy, "proxy_tier": proxy_tier},
            _format_decimal(cost),
        )
        for source, strategy, proxy_tier, cost in _fetch_cost_estimated(session)
    )
    lines.extend(
        _sample(
            "price_monitor_proxy_pool_active_total",
            {"tier": tier, "status": status},
            count,
        )
        for tier, status, count in _proxy_pool_counts(session)
    )
    lines.extend(
        _sample(
            "price_monitor_source_quarantine_total",
            {"status": status},
            count,
        )
        for status, count in _group_counts(session, SourceQuarantineState.status)
    )
    lines.extend(
        _sample(
            "price_monitor_browser_fallback_total",
            {"source": source, "browser_engine": browser_engine},
            count,
        )
        for source, browser_engine, count in _browser_fallback_counts(session)
    )
    lines.extend(
        _sample("price_monitor_image_copy_total", {"status": status}, count)
        for status, count in _image_copy_counts(session)
    )
    lines.extend(
        _sample(
            "price_monitor_extraction_errors_total",
            {"source": source, "error_type": error_type},
            count,
        )
        for source, error_type, count in _extraction_error_counts(session)
    )
    lines.append(f"{CHART_REQUESTS_METRIC} {_metric_counter_value(session)}")
    return "\n".join(lines) + "\n"


def increment_metric_counter(session: Session, name: str) -> None:
    result = session.execute(
        update(MetricCounter)
        .where(MetricCounter.name == name)
        .values(value=MetricCounter.value + 1, updated_at=func.now())
    )
    if result.rowcount:
        session.commit()
        return

    session.add(MetricCounter(name=name, value=1))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        session.execute(
            update(MetricCounter)
            .where(MetricCounter.name == name)
            .values(value=MetricCounter.value + 1, updated_at=func.now())
        )
        session.commit()


def _count(session: Session, column) -> int:
    return int(session.scalar(select(func.count(column))) or 0)


def _count_active_subscriptions(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(UserProductSubscription.id)).where(
                UserProductSubscription.is_active.is_(True)
            )
        )
        or 0
    )


def _group_counts(session: Session, column) -> list[tuple[str, int]]:
    rows = session.execute(
        select(column, func.count()).group_by(column).order_by(column.asc())
    )
    return [(str(label), int(count)) for label, count in rows]


def _notification_counts(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        select(
            NotificationEvent.status,
            NotificationEvent.event_type,
            func.count(),
        )
        .group_by(NotificationEvent.status, NotificationEvent.event_type)
        .order_by(NotificationEvent.status.asc(), NotificationEvent.event_type.asc())
    )
    return [
        (str(status), str(event_type), int(count)) for status, event_type, count in rows
    ]


def _source_event_counts(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        select(
            SourceHealthEvent.source_code,
            SourceHealthEvent.event_type,
            func.count(),
        )
        .group_by(SourceHealthEvent.source_code, SourceHealthEvent.event_type)
        .order_by(
            SourceHealthEvent.source_code.asc(),
            SourceHealthEvent.event_type.asc(),
        )
    )
    return [
        (str(source), str(event_type), int(count)) for source, event_type, count in rows
    ]


def _fetch_attempt_counts(session: Session) -> list[tuple[str, str, str, str, int]]:
    error_type = func.coalesce(FetchAttempt.error_type, "none")
    rows = session.execute(
        select(
            FetchAttempt.source_code,
            FetchAttempt.strategy,
            FetchAttempt.status,
            error_type,
            func.count(),
        )
        .group_by(
            FetchAttempt.source_code,
            FetchAttempt.strategy,
            FetchAttempt.status,
            error_type,
        )
        .order_by(
            FetchAttempt.source_code.asc(),
            FetchAttempt.strategy.asc(),
            FetchAttempt.status.asc(),
            error_type.asc(),
        )
    )
    return [
        (str(source), str(strategy), str(status), str(error_type_value), int(count))
        for source, strategy, status, error_type_value, count in rows
    ]


def _fetch_cost_estimated(session: Session) -> list[tuple[str, str, str, Decimal]]:
    proxy_tier = func.coalesce(ProxyPool.tier, literal("none"))
    rows = session.execute(
        select(
            FetchAttempt.source_code,
            FetchAttempt.strategy,
            proxy_tier,
            func.coalesce(func.sum(FetchAttempt.cost_estimated), 0),
        )
        .select_from(FetchAttempt)
        .outerjoin(ProxyPool, FetchAttempt.proxy_pool_id == ProxyPool.id)
        .group_by(FetchAttempt.source_code, FetchAttempt.strategy, proxy_tier)
        .order_by(
            FetchAttempt.source_code.asc(),
            FetchAttempt.strategy.asc(),
            proxy_tier.asc(),
        )
    )
    return [
        (str(source), str(strategy), str(tier), Decimal(str(cost)))
        for source, strategy, tier, cost in rows
    ]


def _proxy_pool_counts(session: Session) -> list[tuple[str, str, int]]:
    status = case((ProxyPool.enabled.is_(True), "enabled"), else_="disabled")
    rows = session.execute(
        select(ProxyPool.tier, status, func.count())
        .group_by(ProxyPool.tier, status)
        .order_by(ProxyPool.tier.asc(), status.asc())
    )
    return [
        (str(tier), str(status_value), int(count)) for tier, status_value, count in rows
    ]


def _browser_fallback_counts(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        select(FetchAttempt.source_code, FetchAttempt.strategy, func.count())
        .where(FetchAttempt.strategy.in_(BROWSER_FALLBACK_STRATEGIES))
        .group_by(FetchAttempt.source_code, FetchAttempt.strategy)
        .order_by(FetchAttempt.source_code.asc(), FetchAttempt.strategy.asc())
    )
    return [
        (str(source), _browser_engine(str(strategy)), int(count))
        for source, strategy, count in rows
    ]


def _image_copy_counts(session: Session) -> list[tuple[str, int]]:
    object_key_present = and_(
        TrackedProduct.image_object_key.is_not(None),
        TrackedProduct.image_object_key != "",
    )
    object_key_missing = or_(
        TrackedProduct.image_object_key.is_(None),
        TrackedProduct.image_object_key == "",
    )
    image_url_present = and_(
        TrackedProduct.image_url.is_not(None),
        TrackedProduct.image_url != "",
    )
    image_url_missing = or_(
        TrackedProduct.image_url.is_(None),
        TrackedProduct.image_url == "",
    )
    return [
        ("copied", _count_where(session, object_key_present)),
        (
            "external_url",
            _count_where(session, and_(object_key_missing, image_url_present)),
        ),
        ("missing", _count_where(session, and_(object_key_missing, image_url_missing))),
    ]


def _extraction_error_counts(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        select(FetchAttempt.source_code, FetchAttempt.error_type, func.count())
        .where(
            FetchAttempt.status == "failed",
            FetchAttempt.error_type.in_(EXTRACTION_ERROR_TYPES),
        )
        .group_by(FetchAttempt.source_code, FetchAttempt.error_type)
        .order_by(FetchAttempt.source_code.asc(), FetchAttempt.error_type.asc())
    )
    return [
        (str(source), str(error_type), int(count)) for source, error_type, count in rows
    ]


def _count_where(session: Session, predicate) -> int:
    return int(
        session.scalar(select(func.count(TrackedProduct.id)).where(predicate)) or 0
    )


def _metric_counter_value(session: Session) -> int:
    return int(
        session.scalar(
            select(MetricCounter.value).where(
                MetricCounter.name == CHART_REQUESTS_METRIC
            )
        )
        or 0
    )


def _browser_engine(strategy: str) -> str:
    if strategy.endswith("_browser"):
        return strategy.removesuffix("_browser")
    return strategy


def _format_decimal(value: Decimal) -> str:
    return f"{value:.6f}"


def _sample(name: str, labels: dict[str, str], value: int | str) -> str:
    label_text = ",".join(
        f'{label_name}="{_escape_label_value(label_value)}"'
        for label_name, label_value in labels.items()
    )
    return f"{name}{{{label_text}}} {value}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
