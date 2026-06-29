from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.reliability.models import InboxMessage, OutboxEvent
from price_monitor.domains.reliability.outbox import InMemoryPublisher, OutboxPublisher
from price_monitor.domains.reliability.processed_messages import mark_message_processed


def test_outbox_publisher_marks_pending_events_as_sent(session: Session) -> None:
    event = OutboxEvent(
        event_type="watchlist.item_added",
        aggregate_type="watchlist_item",
        aggregate_id="item-1",
        logical_key="watchlist:item-1:created",
        request_id="req-1",
        payload={"watchlist_item_id": "item-1"},
    )
    session.add(event)
    session.commit()

    publisher = InMemoryPublisher()
    published = OutboxPublisher(session=session, publisher=publisher).publish_pending(batch_size=10)

    assert published == 1
    assert publisher.messages[0].routing_key == "watchlist.item_added"
    assert session.get(OutboxEvent, event.id).status == "sent"


def test_inbox_records_make_worker_message_processing_idempotent(session: Session) -> None:
    first = mark_message_processed(
        session=session,
        message_id="event-1",
        consumer="fetch-worker",
        logical_key="fetch:product-1",
    )
    second = mark_message_processed(
        session=session,
        message_id="event-1",
        consumer="fetch-worker",
        logical_key="fetch:product-1",
    )

    assert first is True
    assert second is False
    assert len(session.scalars(select(InboxMessage)).all()) == 1
