from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.core.config import settings
from app.services.cleanup import (
    cleanup_notification_events,
    cleanup_old_fetch_jobs,
    cleanup_price_history,
)
from app.services.scheduler import schedule_due_fetch_jobs
from app.services.source_quarantine import refresh_source_quarantine_states

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.periodic.schedule_due_fetch_jobs_task")
def schedule_due_fetch_jobs_task():
    try:
        return schedule_due_fetch_jobs(settings.scheduler_due_fetch_limit)
    except Exception:
        logger.exception("schedule_due_fetch_jobs_task_failed")
        raise


@celery_app.task(name="app.tasks.periodic.cleanup_old_data_task")
def cleanup_old_data_task() -> dict[str, int]:
    try:
        price_history_deleted = cleanup_price_history(
            settings.cleanup_price_history_retention_days
        )
        fetch_jobs_deleted = cleanup_old_fetch_jobs(
            settings.cleanup_fetch_jobs_retention_days
        )
        notification_events_deleted = cleanup_notification_events(
            settings.cleanup_notification_events_retention_days
        )
    except Exception:
        logger.exception("cleanup_old_data_task_failed")
        raise

    return {
        "price_history_deleted": price_history_deleted,
        "fetch_jobs_deleted": fetch_jobs_deleted,
        "notification_events_deleted": notification_events_deleted,
    }


@celery_app.task(name="app.tasks.periodic.refresh_source_quarantine_task")
def refresh_source_quarantine_task() -> int:
    try:
        return refresh_source_quarantine_states()
    except Exception:
        logger.exception("refresh_source_quarantine_task_failed")
        raise
