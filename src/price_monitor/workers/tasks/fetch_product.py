from datetime import UTC, datetime

from price_monitor.core.config import get_settings
from price_monitor.db.session import get_session_factory
from price_monitor.domains.fetching.http_fetcher import HttpProductPageFetcher
from price_monitor.domains.fetching.managed_unblocker_fetcher import (
    build_managed_unblocker_fetcher,
)
from price_monitor.domains.fetching.service import FetchPipeline
from price_monitor.domains.fetching.source_browser_fetcher import build_source_browser_fetcher
from price_monitor.domains.reliability.models import FetchJob
from price_monitor.domains.sources.service import SourceService
from price_monitor.workers.celery_app import create_celery_app

settings = get_settings()
celery_app = create_celery_app(settings.rabbitmq_url, settings.redis_url)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="price_monitor.workers.tasks.fetch_product",
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=25,
    time_limit=30,
)
def fetch_product(product_id: str, fetch_job_id: str | None = None) -> dict[str, str]:
    with get_session_factory()() as session:
        job = session.get(FetchJob, fetch_job_id) if fetch_job_id is not None else None
        try:
            if job is not None:
                job.status = "running"
                job.status_reason = None
                job.started_at = datetime.now(UTC)
                job.attempt_count += 1
                session.flush()

            stored_settings = SourceService(session).get_settings()
            result = FetchPipeline(
                session,
                direct_fetcher=HttpProductPageFetcher(),
                browser_fetcher=build_source_browser_fetcher(settings, stored_settings),
                managed_unblocker_fetcher=build_managed_unblocker_fetcher(settings),
            ).run(product_id=product_id, fetch_job_id=fetch_job_id)
            if job is not None:
                if result.status in {"ok", "quarantined", "dead_letter"}:
                    job.status = result.status
                else:
                    job.status = "failed"
                job.status_reason = (
                    None if result.status == "ok" else (result.reason or result.status)
                )
                job.finished_at = datetime.now(UTC)
                session.flush()
            session.commit()
        except Exception as exc:
            if job is not None:
                if job.started_at is None:
                    job.started_at = datetime.now(UTC)
                job.status = "dead_letter"
                job.status_reason = type(exc).__name__
                job.finished_at = datetime.now(UTC)
                session.flush()
                session.commit()
            raise
    return {"product_id": product_id, "status": result.status}


def enqueue_fetch_product(product_id: str, fetch_job_id: str | None = None) -> None:
    fetch_product.delay(product_id, fetch_job_id)
