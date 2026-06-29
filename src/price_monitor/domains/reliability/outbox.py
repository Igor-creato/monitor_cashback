from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.reliability.models import OutboxEvent


@dataclass(frozen=True)
class PublishedMessage:
    routing_key: str
    payload: dict[str, object]
    headers: dict[str, str]


class MessagePublisher(Protocol):
    def publish(
        self, *, routing_key: str, payload: dict[str, object], headers: dict[str, str]
    ) -> None:
        """Publish a durable message to the configured broker."""


class InMemoryPublisher:
    def __init__(self) -> None:
        self.messages: list[PublishedMessage] = []

    def publish(
        self, *, routing_key: str, payload: dict[str, object], headers: dict[str, str]
    ) -> None:
        self.messages.append(
            PublishedMessage(routing_key=routing_key, payload=payload, headers=headers)
        )


class OutboxPublisher:
    def __init__(self, *, session: Session, publisher: MessagePublisher) -> None:
        self._session = session
        self._publisher = publisher

    def publish_pending(self, *, batch_size: int) -> int:
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.status == "pending")
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        events = list(self._session.scalars(statement))
        for event in events:
            self._publisher.publish(
                routing_key=event.event_type,
                payload=event.payload,
                headers={
                    "event_id": event.id,
                    "logical_key": event.logical_key,
                    "request_id": event.request_id,
                },
            )
            event.status = "sent"
            event.attempts += 1
            event.published_at = datetime.now(UTC)
        self._session.commit()
        return len(events)
