from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import SourceHealthEvent, SourceQuarantineState

POLICY_WINDOW = timedelta(minutes=30)
DEFAULT_THRESHOLD = 3
COOLDOWN_DURATION = timedelta(minutes=15)
QUARANTINE_DURATION = timedelta(hours=24)
COOLDOWN_STATUS = "cooldown"
QUARANTINED_STATUS = "quarantined"
DISABLED_STATUS = "disabled"
ACTIVE_STATUS = "active"
PARSER_ISSUE_REASON = "parser_issue"


@dataclass(frozen=True)
class EffectiveSourceQuarantineState:
    source_code: str
    status: str
    reason: str | None
    error_type: str | None
    quarantined_until: datetime | None

    @property
    def is_blocked(self) -> bool:
        return self.status in {COOLDOWN_STATUS, QUARANTINED_STATUS, DISABLED_STATUS}


def apply_source_quarantine_policy(
    source_code: str,
    error_type: str,
    *,
    session: Session | None = None,
    now: datetime | None = None,
    threshold: int = DEFAULT_THRESHOLD,
    period: timedelta = POLICY_WINDOW,
) -> SourceQuarantineState:
    if session is not None:
        return _apply_policy(source_code, error_type, session, now, threshold, period)

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        return _apply_policy(
            source_code,
            error_type,
            owned_session,
            now,
            threshold,
            period,
        )


def get_effective_source_quarantine_state(
    source_code: str,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> EffectiveSourceQuarantineState:
    if session is not None:
        return _effective_state(source_code, session, now)

    if SessionLocal is None:
        return EffectiveSourceQuarantineState(
            source_code=source_code,
            status=ACTIVE_STATUS,
            reason=None,
            error_type=None,
            quarantined_until=None,
        )

    with SessionLocal() as owned_session:
        return _effective_state(source_code, owned_session, now)


def _apply_policy(
    source_code: str,
    error_type: str,
    session: Session,
    now: datetime | None,
    threshold: int,
    period: timedelta,
) -> SourceQuarantineState:
    now_utc = _as_utc_naive(now)
    state = _get_or_create_state(source_code, session)

    if state.status == DISABLED_STATUS:
        return state

    if error_type == "captcha_detected":
        _set_state(
            state,
            status=QUARANTINED_STATUS,
            reason="captcha_detected",
            error_type=error_type,
            quarantined_until=now_utc + QUARANTINE_DURATION,
        )
    elif (
        error_type == "http_403"
        and _event_count(
            session,
            source_code,
            error_type,
            cutoff=now_utc - period,
        )
        >= threshold
    ):
        _set_state(
            state,
            status=QUARANTINED_STATUS,
            reason="too_many_403",
            error_type=error_type,
            quarantined_until=now_utc + QUARANTINE_DURATION,
        )
    elif (
        error_type == "http_429"
        and _event_count(
            session,
            source_code,
            error_type,
            cutoff=now_utc - period,
        )
        >= threshold
    ):
        _set_state(
            state,
            status=COOLDOWN_STATUS,
            reason="too_many_429",
            error_type=error_type,
            quarantined_until=now_utc + COOLDOWN_DURATION,
        )
    elif (
        error_type == "parser_error"
        and _event_count(
            session,
            source_code,
            error_type,
            cutoff=now_utc - period,
        )
        >= threshold
    ):
        _set_state(
            state,
            status=ACTIVE_STATUS,
            reason=PARSER_ISSUE_REASON,
            error_type=error_type,
            quarantined_until=None,
        )

    session.commit()
    session.refresh(state)
    return state


def _effective_state(
    source_code: str,
    session: Session,
    now: datetime | None,
) -> EffectiveSourceQuarantineState:
    state = _get_state(source_code, session)
    if state is None:
        return EffectiveSourceQuarantineState(
            source_code=source_code,
            status=ACTIVE_STATUS,
            reason=None,
            error_type=None,
            quarantined_until=None,
        )

    now_utc = _as_utc_naive(now)
    if (
        state.status in {COOLDOWN_STATUS, QUARANTINED_STATUS}
        and state.quarantined_until is not None
        and state.quarantined_until <= now_utc
    ):
        _set_state(
            state,
            status=ACTIVE_STATUS,
            reason=None,
            error_type=None,
            quarantined_until=None,
        )
        session.commit()
        session.refresh(state)

    return EffectiveSourceQuarantineState(
        source_code=state.source_code,
        status=state.status,
        reason=state.reason,
        error_type=state.error_type,
        quarantined_until=state.quarantined_until,
    )


def _get_state(
    source_code: str,
    session: Session,
) -> SourceQuarantineState | None:
    return session.scalar(
        select(SourceQuarantineState)
        .where(SourceQuarantineState.source_code == source_code)
        .limit(1)
    )


def _get_or_create_state(
    source_code: str,
    session: Session,
) -> SourceQuarantineState:
    state = _get_state(source_code, session)
    if state is not None:
        return state

    state = SourceQuarantineState(source_code=source_code, status=ACTIVE_STATUS)
    session.add(state)
    session.flush()
    return state


def _set_state(
    state: SourceQuarantineState,
    *,
    status: str,
    reason: str | None,
    error_type: str | None,
    quarantined_until: datetime | None,
) -> None:
    state.status = status
    state.reason = reason
    state.error_type = error_type
    state.quarantined_until = quarantined_until


def _event_count(
    session: Session,
    source_code: str,
    event_type: str,
    *,
    cutoff: datetime,
) -> int:
    return (
        session.scalar(
            select(func.count(SourceHealthEvent.id)).where(
                SourceHealthEvent.source_code == source_code,
                SourceHealthEvent.event_type == event_type,
                SourceHealthEvent.created_at >= cutoff,
            )
        )
        or 0
    )


def _as_utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
