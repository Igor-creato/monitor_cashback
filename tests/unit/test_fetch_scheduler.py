from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from price_monitor.domains.products.models import Product
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.workers.scheduler import schedule_due_fetch_jobs


def test_schedule_due_fetch_jobs_uses_global_default_when_source_has_default_zero(
    session: Session,
) -> None:
    now = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
    source = SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=1,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    source.fetch_interval_hours = 0
    SourceService(session).update_settings({"price_refresh_interval_hours": "8"})
    product = Product(
        source_domain="example.com",
        canonical_url="https://example.com/p/1",
        canonical_url_hash="hash-1",
        last_fetched_at=now - timedelta(hours=8, minutes=1),
    )
    session.add(product)
    session.flush()
    session.add(
        WatchlistItem(
            user_id="wp:test:1",
            product_id=product.id,
            canonical_url_hash=product.canonical_url_hash,
            active_identity_key="wp:test:1:hash-1",
            target_price_minor=None,
            currency="RUB",
            status="active",
        )
    )
    session.flush()

    jobs = schedule_due_fetch_jobs(session, now=now)

    assert len(jobs) == 1
    assert jobs[0].product_id == product.id
    assert jobs[0].logical_key.startswith(f"scheduler:{product.id}:")


def test_schedule_due_fetch_jobs_uses_explicit_source_override(
    session: Session,
) -> None:
    now = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
    source = SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=2,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    SourceService(session).update_settings({"price_refresh_interval_hours": "8"})
    product = Product(
        source_domain="example.com",
        canonical_url="https://example.com/p/2",
        canonical_url_hash="hash-2",
        last_fetched_at=now - timedelta(hours=2, minutes=1),
    )
    session.add(product)
    session.flush()
    session.add(
        WatchlistItem(
            user_id="wp:test:2",
            product_id=product.id,
            canonical_url_hash=product.canonical_url_hash,
            active_identity_key="wp:test:2:hash-2",
            target_price_minor=None,
            currency="RUB",
            status="active",
        )
    )
    session.flush()

    jobs = schedule_due_fetch_jobs(session, now=now)

    assert source.fetch_interval_hours == 2
    assert len(jobs) == 1
    assert jobs[0].product_id == product.id
