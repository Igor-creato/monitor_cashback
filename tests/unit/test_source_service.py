import pytest
from sqlalchemy.orm import Session

from price_monitor.domains.sources.service import (
    InvalidMonitoredSourceError,
    MonitoredSourceInput,
    SourceService,
)


def test_find_supported_source_matches_domain_and_subdomain(session: Session) -> None:
    service = SourceService(session)
    service.upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert service.find_supported_source("https://example.com/p/1").source_domain == "example.com"
    assert (
        service.find_supported_source("https://shop.example.com/p/1").source_domain == "example.com"
    )


def test_find_supported_source_rejects_paused_source(session: Session) -> None:
    service = SourceService(session)
    service.upsert_source(
        MonitoredSourceInput(
            source_domain="paused.test",
            display_name="Paused",
            logo_url="https://paused.test/logo.png",
            status="paused",
            fetch_interval_hours=12,
            history_retention_days=30,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert service.find_supported_source("https://paused.test/p/1") is None


def test_find_source_for_url_returns_paused_source_for_unavailable_message(
    session: Session,
) -> None:
    service = SourceService(session)
    service.upsert_source(
        MonitoredSourceInput(
            source_domain="paused.test",
            display_name="Paused",
            logo_url="https://paused.test/logo.png",
            status="paused",
            fetch_interval_hours=12,
            history_retention_days=30,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    source = service.find_source_for_url("https://shop.paused.test/p/1")

    assert source.source_domain == "paused.test"
    assert source.status == "paused"


def test_upsert_source_rejects_public_suffix_like_domain(session: Session) -> None:
    service = SourceService(session)

    with pytest.raises(InvalidMonitoredSourceError, match="registrable"):
        service.upsert_source(
            MonitoredSourceInput(
                source_domain="com",
                display_name="Too broad",
                logo_url="https://example.com/logo.png",
                status="active",
                fetch_interval_hours=6,
                history_retention_days=90,
                browser_fallback_allowed=False,
                proxy_pool_id=None,
            )
        )
