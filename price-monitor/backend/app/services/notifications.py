from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models.monitoring import (
    NotificationEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

COOLDOWN = timedelta(hours=24)


def evaluate_price_alerts(tracked_product_id) -> list[NotificationEvent]:
    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as session:
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

        created_events: list[NotificationEvent] = []
        for subscription in subscriptions:
            price_event = _target_price_event(tracked_product, subscription)
            if price_event is not None and not _is_in_cooldown(
                subscription.id,
                "target_price_reached",
            ):
                created_events.append(price_event)
                session.add(price_event)

            effective_event = _target_effective_price_event(
                tracked_product,
                subscription,
                snapshot,
            )
            if effective_event is not None and not _is_in_cooldown(
                subscription.id,
                "target_effective_price_reached",
            ):
                created_events.append(effective_event)
                session.add(effective_event)

        if not created_events:
            return []

        session.commit()
        for event in created_events:
            session.refresh(event)
        return created_events


def _target_price_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
) -> NotificationEvent | None:
    if tracked_product.last_price is None or subscription.target_price is None:
        return None
    if tracked_product.last_price > subscription.target_price:
        return None

    return _notification_event(
        tracked_product,
        subscription,
        "target_price_reached",
        {
            "currency": tracked_product.currency,
            "event_type": "target_price_reached",
            "last_price": _decimal_json(tracked_product.last_price),
            "subscription_id": subscription.id,
            "target_price": _decimal_json(subscription.target_price),
            "tracked_product_id": tracked_product.id,
        },
    )


def _target_effective_price_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    snapshot: TrackedProductCashback | None,
) -> NotificationEvent | None:
    if subscription.target_effective_price is None or snapshot is None:
        return None

    effective_price, source = _effective_price(snapshot)
    if effective_price is None or effective_price > subscription.target_effective_price:
        return None

    return _notification_event(
        tracked_product,
        subscription,
        "target_effective_price_reached",
        {
            "currency": tracked_product.currency,
            "effective_price": _decimal_json(effective_price),
            "effective_price_source": source,
            "event_type": "target_effective_price_reached",
            "last_price": _decimal_json(tracked_product.last_price),
            "subscription_id": subscription.id,
            "target_effective_price": _decimal_json(
                subscription.target_effective_price
            ),
            "tracked_product_id": tracked_product.id,
        },
    )


def _effective_price(
    snapshot: TrackedProductCashback,
) -> tuple[Decimal | None, str | None]:
    if snapshot.effective_price is not None:
        return snapshot.effective_price, "effective_price"
    if snapshot.effective_price_conservative is not None:
        return snapshot.effective_price_conservative, "effective_price_conservative"
    return None, None


def _notification_event(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription,
    event_type: str,
    payload: dict[str, Any],
) -> NotificationEvent:
    return NotificationEvent(
        site_id=subscription.site_id,
        external_user_id=subscription.external_user_id,
        subscription_id=subscription.id,
        tracked_product_id=tracked_product.id,
        event_type=event_type,
        payload_json=_compact_json(payload),
    )


def _is_in_cooldown(subscription_id: int, event_type: str) -> bool:
    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    cutoff = datetime.now(UTC).replace(tzinfo=None) - COOLDOWN
    with SessionLocal() as session:
        existing = session.scalar(
            select(NotificationEvent.id).where(
                NotificationEvent.subscription_id == subscription_id,
                NotificationEvent.event_type == event_type,
                NotificationEvent.created_at >= cutoff,
            )
        )
        return existing is not None


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
