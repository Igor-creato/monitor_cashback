from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import IdempotencyRecord


class IdempotencyKeyMissingError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


def require_idempotency_key(value: str | None) -> str:
    key = (value or "").strip()
    if key == "":
        raise IdempotencyKeyMissingError("idempotency_key_required")
    return key


def run_idempotent(
    session: Session,
    *,
    scope: str,
    idempotency_key: str,
    raw_body: bytes,
    operation: Callable[[], Any],
) -> Any:
    request_hash = hashlib.sha256(raw_body).hexdigest()
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError("idempotency_key_conflict")
        return existing.response_json

    result = operation()
    response_json = jsonable_encoder(result)
    session.add(
        IdempotencyRecord(
            scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=200,
            response_json=response_json,
        )
    )
    session.commit()
    return response_json
