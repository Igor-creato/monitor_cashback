from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.price_compare.live.models import LiveSearchRun


class LiveSearchRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(
        self,
        *,
        query: str,
        city: str,
        stores: list[str],
        limit: int,
        timeout_seconds: int,
    ) -> LiveSearchRun:
        created_at = datetime.now(UTC)
        run = LiveSearchRun(
            run_id=f"live_{uuid4().hex}",
            query=query,
            city=city,
            stores=stores,
            limit=limit,
            timeout_seconds=timeout_seconds,
            status="queued",
            progress_payload={},
            result_payload={},
            created_at=created_at,
            expires_at=created_at + timedelta(hours=24),
        )
        self._session.add(run)
        self._session.commit()
        self._session.refresh(run)
        return run

    def get_run(self, run_id: str) -> LiveSearchRun | None:
        return self._session.scalars(
            select(LiveSearchRun)
            .where(LiveSearchRun.run_id == run_id)
            .execution_options(populate_existing=True)
        ).first()

    def mark_running(self, run_id: str) -> LiveSearchRun | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        run.status = "running"
        run.started_at = datetime.now(UTC)
        self._session.commit()
        self._session.refresh(run)
        return run

    def store_progress(self, run_id: str, progress: dict[str, object]) -> LiveSearchRun | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        run.progress_payload = dict(progress)
        self._session.commit()
        self._session.refresh(run)
        return run

    def store_result(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, object],
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> LiveSearchRun | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        run.status = status
        run.result_payload = dict(result)
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = datetime.now(UTC)
        self._session.commit()
        self._session.refresh(run)
        return run
