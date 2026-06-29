from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from price_monitor.domains.reliability.models import InboxMessage


def mark_message_processed(
    *, session: Session, message_id: str, consumer: str, logical_key: str
) -> bool:
    existing = session.scalar(
        select(InboxMessage).where(
            InboxMessage.message_id == message_id,
            InboxMessage.consumer == consumer,
        )
    )
    if existing is not None:
        return False

    session.add(InboxMessage(message_id=message_id, consumer=consumer, logical_key=logical_key))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return False
    return True
