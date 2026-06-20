from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.cashback_api import (
    CashbackAPIAuthError,
    CashbackAPIBadResponseError,
    CashbackAPIClient,
    CashbackAPINotFoundError,
)
from app.db import SessionLocal
from app.models.monitoring import (
    MarketplaceConnection,
    MarketplaceSyncSession,
    NotificationEvent,
    NotificationPreference,
    PriceHistory,
    ProductMatchGroup,
    ProductOffer,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.services.user_limits import (
    UserPriceMonitorLimits,
    get_price_monitor_limits,
)

CHANNEL_EMAIL = "email"
DEFAULT_COOLDOWN_MINUTES = 1440
DEFAULT_DROP_THRESHOLD_PERCENT = Decimal("5.00")
SYNC_FAILURE_NOTIFICATION_THRESHOLD = 3
MAX_DELIVERY_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)
NEW_MINIMUM_WINDOWS = (7, 30, 90)

LimitsProvider = Callable[[str, str], UserPriceMonitorLimits | Any]


@dataclass(frozen=True)
class _Preference:
    enabled: bool
    cooldown_minutes: int
    drop_threshold_percent: Decimal


@dataclass(frozen=True)
class _Candidate:
    event_type: str
    dedup_key: str
    payload: dict[str, Any]
    subscription: UserProductSubscription | None = None
    tracked_product: TrackedProduct | None = None
    connection: MarketplaceConnection | None = None


def evaluate_price_alerts(
    tracked_product_id,
    *,
    now: datetime | None = None,
    limits_provider: LimitsProvider = get_price_monitor_limits,
    session: Session | None = None,
) -> list[NotificationEvent]:
    now_utc = _as_utc_naive(now)
    if session is not None:
        return _evaluate_price_alerts_in_session(
            session,
            int(tracked_product_id),
            now=now_utc,
            limits_provider=limits_provider,
        )

    if SessionLocal is None:
        raise ValueError("Database is not configured.")
    with SessionLocal() as db_session:
        return _evaluate_price_alerts_in_session(
            db_session,
            int(tracked_product_id),
            now=now_utc,
            limits_provider=limits_provider,
        )


def evaluate_connection_alerts(
    connection_id: int,
    *,
    now: datetime | None = None,
    reason: str | None = None,
    limits_provider: LimitsProvider = get_price_monitor_limits,
    session: Session | None = None,
) -> list[NotificationEvent]:
    now_utc = _as_utc_naive(now)
    if session is not None:
        return _evaluate_connection_alerts_in_session(
            session,
            int(connection_id),
            now=now_utc,
            reason=reason,
            limits_provider=limits_provider,
        )

    if SessionLocal is None:
        raise ValueError("Database is not configured.")
    with SessionLocal() as db_session:
        return _evaluate_connection_alerts_in_session(
            db_session,
            int(connection_id),
            now=now_utc,
            reason=reason,
            limits_provider=limits_provider,
        )


def dispatch_pending_notifications(
    *,
    limit: int,
    now: datetime | None = None,
    client: CashbackAPIClient | None = None,
) -> dict[str, int]:
    if SessionLocal is None:
        raise ValueError("Database is not configured.")
    now_utc = _as_utc_naive(now)
    api_client = client or CashbackAPIClient()
    result = {"sent": 0, "failed": 0, "retry": 0}

    with SessionLocal() as session:
        events = session.scalars(
            select(NotificationEvent)
            .where(
                NotificationEvent.status == "pending",
                NotificationEvent.channel == CHANNEL_EMAIL,
                (NotificationEvent.next_attempt_at.is_(None))
                | (NotificationEvent.next_attempt_at <= now_utc),
            )
            .order_by(NotificationEvent.created_at.asc(), NotificationEvent.id.asc())
            .limit(limit)
        ).all()

        for event in events:
            try:
                response = api_client.send_price_monitor_notification(
                    _delivery_payload(event)
                )
            except (
                CashbackAPIAuthError,
                CashbackAPIBadResponseError,
                CashbackAPINotFoundError,
            ) as exc:
                _mark_delivery_failed(event, "terminal", str(exc), now_utc)
                result["failed"] += 1
                continue
            except Exception as exc:
                _mark_delivery_retry(event, "transient", str(exc), now_utc)
                if event.status == "failed":
                    result["failed"] += 1
                else:
                    result["retry"] += 1
                continue

            if not isinstance(response, dict) or response.get("status") not in {
                "queued",
                "sent",
            }:
                _mark_delivery_failed(event, "bad_response", "bad_response", now_utc)
                result["failed"] += 1
                continue

            event.status = "sent"
            event.sent_at = now_utc
            event.next_attempt_at = None
            event.last_error_type = None
            event.error_text = None
            result["sent"] += 1

        session.commit()
    return result


def _evaluate_price_alerts_in_session(
    session: Session,
    tracked_product_id: int,
    *,
    now: datetime,
    limits_provider: LimitsProvider,
) -> list[NotificationEvent]:
    tracked_product = session.get(TrackedProduct, tracked_product_id)
    if tracked_product is None:
        return []

    snapshot = session.scalar(
        select(TrackedProductCashback).where(
            TrackedProductCashback.tracked_product_id == tracked_product_id
        )
    )
    subscriptions = session.scalars(
        select(UserProductSubscription).where(
            UserProductSubscription.tracked_product_id == tracked_product_id,
            UserProductSubscription.is_active.is_(True),
        )
    ).all()
    history = _price_history(session, tracked_product_id)

    created_events: list[NotificationEvent] = []
    for subscription in subscriptions:
        candidates = [
            _target_price_event(tracked_product, subscription),
            _target_effective_price_event(tracked_product, subscription, snapshot),
            _price_drop_event(tracked_product, subscription, history, session),
            *_new_minimum_events(tracked_product, subscription, history, now),
            _cheaper_offer_event(tracked_product, subscription, session),
            _back_in_stock_event(tracked_product, subscription, history),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            event = _create_event_if_allowed(
                session,
                candidate,
                now=now,
                limits_provider=limits_provider,
            )
            if event is not None:
                created_events.append(event)

    if created_events:
        session.commit()
        for event in created_events:
            session.refresh(event)
    return created_events


def _evaluate_connection_alerts_in_session(
    session: Session,
    connection_id: int,
    *,
    now: datetime,
    reason: str | None,
    limits_provider: LimitsProvider,
) -> list[NotificationEvent]:
    connection = session.get(MarketplaceConnection, connection_id)
    if connection is None:
        return []

    candidates: list[_Candidate] = []
    if connection.status == "reconnect_required":
        reconnect_reason = reason or connection.reconnect_reason or "unknown"
        candidates.append(
            _Candidate(
                event_type="reconnect_required",
                dedup_key=(
                    f"connection:{connection.id}:reconnect_required:"
                    f"{reconnect_reason}"
                ),
                connection=connection,
                payload={
                    "event_type": "reconnect_required",
                    "connection_id": connection.id,
                    "marketplace": connection.marketplace,
                    "reason": reconnect_reason,
                },
            )
        )
    elif connection.status == "sync_failed_retryable":
        failure_count = _consecutive_failed_sync_count(session, connection.id)
        if failure_count >= SYNC_FAILURE_NOTIFICATION_THRESHOLD:
            failure_reason = reason or connection.reconnect_reason or "sync_failed"
            candidates.append(
                _Candidate(
                    event_type="sync_failed_repeated",
                    dedup_key=(
                        f"connection:{connection.id}:sync_failed_repeated:"
                        f"{failure_reason}"
                    ),
                    connection=connection,
                    payload={
                        "event_type": "sync_failed_repeated",
                        "connection_id": connection.id,
                        "marketplace": connection.marketplace,
                        "reason": failure_reason,
                        "failure_count": failure_count,
                    },
                )
            )

    created_events: list[NotificationEvent] = []
    for candidate in candidates:
        event = _create_event_if_allowed(
            session,
            candidate,
            now=now,
            limits_provider=limits_provider,
        )
        if event is not None:
            created_events.append(event)

    if created_events:
        session.commit()
        for event in created_events:
            session.refresh(event)
    return created_events


def _target_price_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
) -> _Candidate | None:
    if tracked_product.last_price is None or subscription.target_price is None:
        return None
    if tracked_product.last_price > subscription.target_price:
        return None

    return _product_candidate(
        tracked_product,
        subscription,
        "target_price_reached",
        f"subscription:{subscription.id}:target_price_reached:"
        f"{_decimal_json(tracked_product.last_price)}",
        {
            "target_price": _decimal_json(subscription.target_price),
            "last_price": _decimal_json(tracked_product.last_price),
        },
    )


def _target_effective_price_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    snapshot: TrackedProductCashback | None,
) -> _Candidate | None:
    if subscription.target_effective_price is None or snapshot is None:
        return None

    effective_price, source = _effective_price(snapshot)
    if effective_price is None or effective_price > subscription.target_effective_price:
        return None

    return _product_candidate(
        tracked_product,
        subscription,
        "target_effective_price_reached",
        f"subscription:{subscription.id}:target_effective_price_reached:"
        f"{_decimal_json(effective_price)}",
        {
            "target_effective_price": _decimal_json(
                subscription.target_effective_price
            ),
            "effective_price": _decimal_json(effective_price),
            "effective_price_source": source,
            "last_price": _decimal_json(tracked_product.last_price),
        },
    )


def _price_drop_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    history: list[PriceHistory],
    session: Session,
) -> _Candidate | None:
    if tracked_product.last_price is None or len(history) < 2:
        return None
    previous = history[1]
    if previous.price_current <= tracked_product.last_price:
        return None

    drop_percent = (
        (previous.price_current - tracked_product.last_price)
        / previous.price_current
        * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    preference = _preference(
        session,
        site_id=subscription.site_id,
        external_user_id=subscription.external_user_id,
        event_type="price_drop",
    )
    if drop_percent < preference.drop_threshold_percent:
        return None

    return _product_candidate(
        tracked_product,
        subscription,
        "price_drop",
        f"subscription:{subscription.id}:price_drop:"
        f"{_decimal_json(tracked_product.last_price)}",
        {
            "previous_price": _decimal_json(previous.price_current),
            "last_price": _decimal_json(tracked_product.last_price),
            "drop_percent": _decimal_json(drop_percent),
        },
    )


def _new_minimum_events(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    history: list[PriceHistory],
    now: datetime,
) -> list[_Candidate]:
    if tracked_product.last_price is None:
        return []
    events: list[_Candidate] = []
    for window_days in NEW_MINIMUM_WINDOWS:
        cutoff = now - timedelta(days=window_days)
        points = [point for point in history if point.fetched_at >= cutoff]
        if not points:
            continue
        oldest_required = now - timedelta(days=window_days - 1)
        if not any(point.fetched_at <= oldest_required for point in points):
            continue
        prior_prices = [
            point.price_current
            for point in points
            if point.price_current is not None and point.fetched_at < now
        ]
        if not prior_prices or tracked_product.last_price >= min(prior_prices):
            continue
        event_type = f"new_minimum_{window_days}d"
        events.append(
            _product_candidate(
                tracked_product,
                subscription,
                event_type,
                f"subscription:{subscription.id}:{event_type}:"
                f"{_decimal_json(tracked_product.last_price)}",
                {
                    "window_days": window_days,
                    "last_price": _decimal_json(tracked_product.last_price),
                    "previous_min_price": _decimal_json(min(prior_prices)),
                },
            )
        )
    return events


def _cheaper_offer_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    session: Session,
) -> _Candidate | None:
    if tracked_product.last_price is None:
        return None
    offer = session.scalar(
        select(ProductOffer)
        .join(ProductMatchGroup)
        .where(
            ProductMatchGroup.tracked_product_id == tracked_product.id,
            ProductOffer.price < tracked_product.last_price,
            ProductOffer.availability.in_(("in_stock", "in stock", "available")),
        )
        .order_by(ProductOffer.price.asc(), ProductOffer.id.asc())
    )
    if offer is None:
        return None
    return _product_candidate(
        tracked_product,
        subscription,
        "cheaper_offer_found",
        f"subscription:{subscription.id}:cheaper_offer_found:{offer.id}:"
        f"{_decimal_json(offer.price)}",
        {
            "offer_id": offer.id,
            "store_code": offer.store.store_code,
            "source_code": offer.source_code,
            "offer_price": _decimal_json(offer.price),
            "last_price": _decimal_json(tracked_product.last_price),
            "match_label": offer.match_label,
        },
    )


def _back_in_stock_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    history: list[PriceHistory],
) -> _Candidate | None:
    if len(history) < 2:
        return None
    latest, previous = history[0], history[1]
    if not latest.availability or previous.availability:
        return None
    return _product_candidate(
        tracked_product,
        subscription,
        "back_in_stock",
        f"subscription:{subscription.id}:back_in_stock:{latest.fetched_at.isoformat()}",
        {
            "last_price": _decimal_json(tracked_product.last_price),
            "fetched_at": _datetime_json(latest.fetched_at),
        },
    )


def _product_candidate(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    event_type: str,
    dedup_key: str,
    payload: dict[str, Any],
) -> _Candidate:
    base_payload = {
        "currency": tracked_product.currency,
        "event_type": event_type,
        "subscription_id": subscription.id,
        "tracked_product_id": tracked_product.id,
    }
    base_payload.update(payload)
    return _Candidate(
        event_type=event_type,
        dedup_key=dedup_key,
        payload=base_payload,
        subscription=subscription,
        tracked_product=tracked_product,
    )


def _create_event_if_allowed(
    session: Session,
    candidate: _Candidate,
    *,
    now: datetime,
    limits_provider: LimitsProvider,
) -> NotificationEvent | None:
    site_id, external_user_id = _candidate_owner(candidate)
    preference = _preference(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
        event_type=candidate.event_type,
    )
    if not preference.enabled:
        return None
    if _existing_dedup(session, candidate, site_id, external_user_id):
        return None
    if _is_in_cooldown(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
        event_type=candidate.event_type,
        cooldown_minutes=preference.cooldown_minutes,
        now=now,
    ):
        return None

    status = "pending"
    next_attempt_at = now
    if _daily_limit_reached(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
        limits_provider=limits_provider,
        now=now,
    ):
        status = "skipped"
        next_attempt_at = None

    event = NotificationEvent(
        site_id=site_id,
        external_user_id=external_user_id,
        subscription_id=(
            candidate.subscription.id if candidate.subscription is not None else None
        ),
        tracked_product_id=(
            candidate.tracked_product.id
            if candidate.tracked_product is not None
            else None
        ),
        connection_id=(
            candidate.connection.id if candidate.connection is not None else None
        ),
        event_type=candidate.event_type,
        channel=CHANNEL_EMAIL,
        dedup_key=candidate.dedup_key,
        status=status,
        payload_json=_compact_json(candidate.payload),
        created_at=now,
        next_attempt_at=next_attempt_at,
    )
    session.add(event)
    session.flush()
    return event


def _candidate_owner(candidate: _Candidate) -> tuple[str, str]:
    if candidate.subscription is not None:
        return candidate.subscription.site_id, candidate.subscription.external_user_id
    if candidate.connection is not None:
        return candidate.connection.site_id, candidate.connection.external_user_id
    raise ValueError("notification_candidate_owner_missing")


def _preference(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    event_type: str,
) -> _Preference:
    preference = session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.site_id == site_id,
            NotificationPreference.external_user_id == external_user_id,
            NotificationPreference.event_type == event_type,
            NotificationPreference.channel == CHANNEL_EMAIL,
        )
    )
    if preference is None:
        return _Preference(
            enabled=True,
            cooldown_minutes=DEFAULT_COOLDOWN_MINUTES,
            drop_threshold_percent=DEFAULT_DROP_THRESHOLD_PERCENT,
        )
    return _Preference(
        enabled=preference.enabled,
        cooldown_minutes=preference.cooldown_minutes,
        drop_threshold_percent=preference.drop_threshold_percent,
    )


def _existing_dedup(
    session: Session,
    candidate: _Candidate,
    site_id: str,
    external_user_id: str,
) -> bool:
    existing = session.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.site_id == site_id,
            NotificationEvent.external_user_id == external_user_id,
            NotificationEvent.event_type == candidate.event_type,
            NotificationEvent.channel == CHANNEL_EMAIL,
            NotificationEvent.dedup_key == candidate.dedup_key,
        )
    )
    return existing is not None


def _is_in_cooldown(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    event_type: str,
    cooldown_minutes: int,
    now: datetime,
) -> bool:
    cutoff = now - timedelta(minutes=max(cooldown_minutes, 0))
    existing = session.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.site_id == site_id,
            NotificationEvent.external_user_id == external_user_id,
            NotificationEvent.event_type == event_type,
            NotificationEvent.channel == CHANNEL_EMAIL,
            NotificationEvent.created_at >= cutoff,
        )
    )
    return existing is not None


def _daily_limit_reached(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    limits_provider: LimitsProvider,
    now: datetime,
) -> bool:
    limits = limits_provider(site_id, external_user_id)
    alerts_per_day = getattr(getattr(limits, "limits", None), "alerts_per_day", 0)
    if alerts_per_day <= 0:
        return True
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    used = session.scalar(
        select(func.count(NotificationEvent.id)).where(
            NotificationEvent.site_id == site_id,
            NotificationEvent.external_user_id == external_user_id,
            NotificationEvent.status.in_(("pending", "sent")),
            NotificationEvent.created_at >= start,
            NotificationEvent.created_at < end,
        )
    )
    return (used or 0) >= alerts_per_day


def _price_history(session: Session, tracked_product_id: int) -> list[PriceHistory]:
    return list(
        session.scalars(
            select(PriceHistory)
            .where(PriceHistory.tracked_product_id == tracked_product_id)
            .order_by(PriceHistory.fetched_at.desc(), PriceHistory.id.desc())
        ).all()
    )


def _consecutive_failed_sync_count(session: Session, connection_id: int) -> int:
    rows = session.scalars(
        select(MarketplaceSyncSession)
        .where(MarketplaceSyncSession.connection_id == connection_id)
        .order_by(
            MarketplaceSyncSession.started_at.desc(),
            MarketplaceSyncSession.id.desc(),
        )
        .limit(SYNC_FAILURE_NOTIFICATION_THRESHOLD)
    ).all()
    count = 0
    for row in rows:
        if row.status != "failed":
            break
        count += 1
    return count


def _effective_price(
    snapshot: TrackedProductCashback,
) -> tuple[Decimal | None, str | None]:
    if snapshot.effective_price is not None:
        return snapshot.effective_price, "effective_price"
    if snapshot.effective_price_conservative is not None:
        return snapshot.effective_price_conservative, "effective_price_conservative"
    return None, None


def _delivery_payload(event: NotificationEvent) -> dict[str, Any]:
    body_data = json.loads(event.payload_json or "{}")
    return {
        "notification_id": event.id,
        "event_type": event.event_type,
        "channel": event.channel,
        "site_id": event.site_id,
        "external_user_id": event.external_user_id,
        "dedup_key": event.dedup_key,
        "template": f"price_monitor_{event.event_type}",
        "subject_data": {},
        "body_data": body_data,
        "created_at": _datetime_json(event.created_at),
    }


def _mark_delivery_retry(
    event: NotificationEvent,
    error_type: str,
    error_text: str,
    now: datetime,
) -> None:
    event.delivery_attempts = (event.delivery_attempts or 0) + 1
    event.last_error_type = error_type
    event.error_text = _safe_error_text(error_text)
    if event.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
        event.status = "failed"
        event.next_attempt_at = None
        return
    event.status = "pending"
    event.next_attempt_at = now + RETRY_DELAY


def _mark_delivery_failed(
    event: NotificationEvent,
    error_type: str,
    error_text: str,
    now: datetime,
) -> None:
    del now
    event.delivery_attempts = (event.delivery_attempts or 0) + 1
    event.status = "failed"
    event.next_attempt_at = None
    event.last_error_type = error_type
    event.error_text = _safe_error_text(error_text)


def _safe_error_text(value: str) -> str:
    return value[:500]


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _datetime_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _as_utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
