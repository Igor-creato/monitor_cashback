from __future__ import annotations

from importlib import import_module

from celery import Celery

from app.core.config import settings

celery_app = Celery("price_monitor", broker=settings.rabbitmq_url)

celery_app.conf.beat_schedule = {
    "schedule-due-fetch-jobs": {
        "task": "app.tasks.periodic.schedule_due_fetch_jobs_task",
        "schedule": settings.celery_scheduler_interval_seconds,
    },
    "cleanup-old-data": {
        "task": "app.tasks.periodic.cleanup_old_data_task",
        "schedule": settings.celery_cleanup_interval_seconds,
    },
    "refresh-source-quarantine": {
        "task": "app.tasks.periodic.refresh_source_quarantine_task",
        "schedule": settings.celery_quarantine_refresh_interval_seconds,
    },
}

import_module("app.tasks.http_fetch")
import_module("app.tasks.periodic")
