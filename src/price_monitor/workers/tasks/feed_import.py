from __future__ import annotations

from price_monitor.db.session import get_session_factory
from price_monitor.price_compare.feed_importer import AffiliateFeedImportService
from price_monitor.workers.celery_app import celery_app


@celery_app.task(name="price_monitor.feed_import.run")  # type: ignore[untyped-decorator]
def run_feed_import() -> dict[str, object]:
    factory = get_session_factory()
    with factory() as session:
        summary = AffiliateFeedImportService(session).import_configured_feeds()
        return {
            "status": summary.status,
            "created_count": summary.created_count,
            "updated_count": summary.updated_count,
            "skipped_count": summary.skipped_count,
            "quarantined_count": summary.quarantined_count,
        }
