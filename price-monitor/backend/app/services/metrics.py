from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.monitoring import (
    FetchJob,
    NotificationEvent,
    SourceHealthEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)


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
    return "\n".join(lines) + "\n"


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


def _sample(name: str, labels: dict[str, str], value: int) -> str:
    label_text = ",".join(
        f'{label_name}="{_escape_label_value(label_value)}"'
        for label_name, label_value in labels.items()
    )
    return f"{name}{{{label_text}}} {value}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
