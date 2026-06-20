import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models.monitoring import IncomingHmacReplayRecord

MAX_TIMESTAMP_SKEW_SECONDS = 300
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def current_unix_time() -> int:
    return int(time.time())


async def verify_incoming_hmac_request(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    expected_site_id = settings.price_monitor_incoming_site_id.strip()
    secret = settings.price_monitor_incoming_secret.get_secret_value()
    if expected_site_id == "" or secret == "":
        raise HTTPException(status_code=401, detail="Incoming authentication required.")

    site_id = request.headers.get("X-Savello-Site", "").strip()
    timestamp = request.headers.get("X-Savello-Timestamp", "").strip()
    signature = request.headers.get("X-Savello-Signature", "").strip()
    if site_id == "" or timestamp == "" or signature == "":
        raise HTTPException(status_code=401, detail="Incoming authentication required.")

    if site_id != expected_site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    if not timestamp.isdigit():
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    request_time = int(timestamp)
    if abs(current_unix_time() - request_time) > MAX_TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    raw_body = await request.body()
    expected_signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    if request.method.upper() in MUTATING_METHODS:
        _reject_replayed_mutating_request(
            session,
            site_id=site_id,
            method=request.method.upper(),
            path=request.url.path,
            timestamp=request_time,
            signature=signature,
            raw_body=raw_body,
        )


def _reject_replayed_mutating_request(
    session: Session,
    *,
    site_id: str,
    method: str,
    path: str,
    timestamp: int,
    signature: str,
    raw_body: bytes,
) -> None:
    cutoff = current_unix_time() - MAX_TIMESTAMP_SKEW_SECONDS
    session.execute(
        delete(IncomingHmacReplayRecord).where(
            IncomingHmacReplayRecord.timestamp < cutoff
        )
    )
    session.add(
        IncomingHmacReplayRecord(
            site_id=site_id,
            method=method,
            path=path,
            timestamp=timestamp,
            signature_hash=hashlib.sha256(signature.encode()).hexdigest(),
            body_hash=hashlib.sha256(raw_body).hexdigest(),
            seen_at=datetime.now(UTC),
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=403,
            detail="Incoming authentication failed.",
        ) from exc
