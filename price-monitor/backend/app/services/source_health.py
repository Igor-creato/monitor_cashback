from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import SourceHealthEvent

PRICE_FETCH_FAILURE_EVENTS = frozenset(
    {
        "timeout",
        "http_403",
        "http_429",
        "parser_error",
        "captcha_detected",
        "price_not_found",
    }
)
CASHBACK_API_ERROR_EVENT = "cashback_api_error"
SUCCESS_EVENT = "success"


@dataclass(frozen=True)
class SourceHealthSummary:
    source_code: str
    success_count: int
    failure_count: int
    price_fetch_failure_count: int
    cashback_api_error_count: int
    total_count: int


def record_source_event(
    source_code: str,
    event_type: str,
    *,
    status_code: int | None = None,
    response_ms: int | None = None,
    session: Session | None = None,
) -> SourceHealthEvent:
    event = SourceHealthEvent(
        source_code=source_code,
        event_type=event_type,
        status_code=status_code,
        response_ms=response_ms,
    )

    if session is not None:
        session.add(event)
        session.commit()
        session.refresh(event)
        return event

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        owned_session.add(event)
        owned_session.commit()
        owned_session.refresh(event)
        return event


def get_source_health_summary(
    source_code: str,
    *,
    session: Session | None = None,
) -> SourceHealthSummary:
    if session is not None:
        return _summary(source_code, session)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _summary(source_code, owned_session)


def _summary(source_code: str, session: Session) -> SourceHealthSummary:
    success_count = _count_events(session, source_code, (SUCCESS_EVENT,))
    price_fetch_failure_count = _count_events(
        session,
        source_code,
        PRICE_FETCH_FAILURE_EVENTS,
    )
    cashback_api_error_count = _count_events(
        session,
        source_code,
        (CASHBACK_API_ERROR_EVENT,),
    )
    failure_count = price_fetch_failure_count + cashback_api_error_count

    return SourceHealthSummary(
        source_code=source_code,
        success_count=success_count,
        failure_count=failure_count,
        price_fetch_failure_count=price_fetch_failure_count,
        cashback_api_error_count=cashback_api_error_count,
        total_count=success_count + failure_count,
    )


def _count_events(
    session: Session,
    source_code: str,
    event_types: frozenset[str] | tuple[str, ...],
) -> int:
    return (
        session.scalar(
            select(func.count(SourceHealthEvent.id)).where(
                SourceHealthEvent.source_code == source_code,
                SourceHealthEvent.event_type.in_(event_types),
            )
        )
        or 0
    )
