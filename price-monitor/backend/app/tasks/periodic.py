from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.core.config import settings
from app.db import SessionLocal
from app.services.cleanup import (
    cleanup_notification_events,
    cleanup_old_fetch_jobs,
    cleanup_price_history,
)
from app.services.marketplace_sync_worker import sync_due_marketplace_connections
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


@celery_app.task(name="app.tasks.periodic.sync_due_marketplace_connections_task")
def sync_due_marketplace_connections_task() -> dict[str, int]:
    try:
        if SessionLocal is None:
            raise ValueError("Database is not configured.")
        with SessionLocal() as session:
            report = sync_due_marketplace_connections(
                session,
                limit=settings.marketplace_sync_due_limit,
            )
    except Exception:
        logger.exception("sync_due_marketplace_connections_task_failed")
        raise

    return {
        "processed_connections": report.processed_connections,
        "skipped_connections": report.skipped_connections,
        "synced_collections": report.synced_collections,
        "failed_collections": report.failed_collections,
        "imported_items": report.imported_items,
        "tracked_products_updated": report.tracked_products_updated,
    }
