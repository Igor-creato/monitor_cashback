from __future__ import annotations

from importlib import import_module

from celery import Celery

from app.core.config import settings

celery_app = Celery("price_monitor", broker=settings.rabbitmq_url)

import_module("app.tasks.http_fetch")
