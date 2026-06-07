from __future__ import annotations

from app.celery_app import celery_app
from app.fetchers.http_fetcher import HTTPPriceFetcher
from app.services.fetch_job_runner import run_http_fetch_job


@celery_app.task(name="app.tasks.http_fetch.http_fetch_job")
def http_fetch_job(job_id: int):
    return run_http_fetch_job(job_id, HTTPPriceFetcher())
