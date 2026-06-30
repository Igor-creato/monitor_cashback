from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.reliability.models import IdempotencyRecord


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request body."""


@dataclass(frozen=True)
class IdempotencyReplay:
    status_code: int
    response_body: dict[str, Any]


def get_replay_or_reserve(
    *, session: Session, key: str, route: str, request_hash: str
) -> IdempotencyRecord | IdempotencyReplay:
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.key == key,
            IdempotencyRecord.route == route,
        )
    )
    if existing is None:
        record = IdempotencyRecord(
            key=key, route=route, request_hash=request_hash, status="pending"
        )
        session.add(record)
        session.flush()
        return record

    if existing.request_hash != request_hash:
        raise IdempotencyConflictError("idempotency key reused with a different request body")
    if existing.status == "pending":
        raise IdempotencyConflictError("idempotency request with this key is already in progress")
    if (
        existing.status == "completed"
        and existing.response_status is not None
        and existing.response_body is not None
    ):
        return IdempotencyReplay(
            status_code=existing.response_status,
            response_body=existing.response_body,
        )
    return existing


def complete_idempotency_record(
    *, record: IdempotencyRecord, status_code: int, response_body: dict[str, Any]
) -> None:
    record.status = "completed"
    record.response_status = status_code
    record.response_body = response_body
