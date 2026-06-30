from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import AlertEvent, OutboxEvent
from price_monitor.domains.watchlist.models import WatchlistItem


class NotificationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate_product(
        self,
        product_id: str,
        now: datetime,
    ) -> list[AlertEvent]:
        product = self._session.get(Product, product_id)
        if product is None or product.current_price_minor is None or product.currency is None:
            return []

        alerts: list[AlertEvent] = []
        watchlist_items = self._session.scalars(
            select(WatchlistItem).where(
                WatchlistItem.product_id == product_id,
                WatchlistItem.status == "active",
                WatchlistItem.target_price_minor.is_not(None),
            )
        ).all()
        for item in watchlist_items:
            assert item.target_price_minor is not None
            if product.current_price_minor > item.target_price_minor:
                continue

            dedup_key = (
                f"price-target:{item.id}:{item.target_price_minor}:{product.current_price_minor}"
            )
            existing = self._session.scalar(
                select(AlertEvent).where(AlertEvent.dedup_key == dedup_key)
            )
            if existing is not None:
                continue

            alert = self._create_alert_event(
                item=item,
                product=product,
                dedup_key=dedup_key,
                now=now,
            )
            if alert is None:
                continue

            alerts.append(alert)

        self._session.flush()
        return alerts

    def _create_alert_event(
        self,
        *,
        item: WatchlistItem,
        product: Product,
        dedup_key: str,
        now: datetime,
    ) -> AlertEvent | None:
        assert item.target_price_minor is not None
        assert product.current_price_minor is not None
        assert product.currency is not None

        alert = AlertEvent(
            watchlist_item_id=item.id,
            product_id=product.id,
            user_id=item.user_id,
            target_price_minor=item.target_price_minor,
            observed_price_minor=product.current_price_minor,
            currency=product.currency,
            dedup_key=dedup_key,
            status="pending",
            created_at=now.astimezone(UTC),
        )
        savepoint = self._session.begin_nested()
        try:
            self._session.add(alert)
            self._session.flush()

            outbox_event = OutboxEvent(
                event_type="notification.price_target_reached",
                aggregate_type="alert_event",
                aggregate_id=alert.id,
                logical_key=dedup_key,
                request_id=f"notification:{alert.id}",
                payload={
                    "alert_event_id": alert.id,
                    "watchlist_item_id": item.id,
                    "product_id": product.id,
                    "user_id": item.user_id,
                    "target_price_minor": item.target_price_minor,
                    "observed_price_minor": product.current_price_minor,
                    "currency": product.currency,
                },
                created_at=now.astimezone(UTC),
            )
            self._session.add(outbox_event)
            self._session.flush()
        except IntegrityError:
            savepoint.rollback()
            if "outbox_event" in locals():
                self._discard_pending(outbox_event)
            self._discard_pending(alert)
            return None

        savepoint.commit()
        return alert

    def _discard_pending(self, model: AlertEvent | OutboxEvent) -> None:
        if model in self._session:
            self._session.expunge(model)
