from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import FetchJob
from price_monitor.domains.sources.models import MonitoredSource
from price_monitor.domains.sources.service import SourceService
from price_monitor.domains.watchlist.models import WatchlistItem


def schedule_due_fetch_jobs(
    session: Session,
    *,
    now: datetime,
    limit: int = 100,
) -> list[FetchJob]:
    source_service = SourceService(session)
    rows = session.execute(
        select(WatchlistItem, Product, MonitoredSource)
        .join(Product, WatchlistItem.product_id == Product.id)
        .join(MonitoredSource, Product.source_domain == MonitoredSource.source_domain)
        .where(WatchlistItem.status == "active", MonitoredSource.status == "active")
        .order_by(WatchlistItem.updated_at.asc(), WatchlistItem.id.asc())
        .limit(limit)
    ).all()

    jobs: list[FetchJob] = []
    seen_product_ids: set[str] = set()
    for _, product, source in rows:
        if product.id in seen_product_ids:
            continue
        seen_product_ids.add(product.id)

        interval_hours = source_service.effective_fetch_interval_hours(source)
        due_at = now - timedelta(hours=interval_hours)
        if product.last_fetched_at is not None and product.last_fetched_at > due_at:
            continue

        logical_key = f"scheduler:{product.id}:{now.isoformat()}"
        existing = session.scalar(select(FetchJob).where(FetchJob.logical_key == logical_key))
        if existing is not None:
            jobs.append(existing)
            continue

        job = FetchJob(
            product_id=product.id,
            logical_key=logical_key,
            status="queued",
            scheduled_for=now,
        )
        session.add(job)
        jobs.append(job)

    session.flush()
    return jobs
