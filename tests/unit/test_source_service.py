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


def test_monitor_settings_include_joom_provider_defaults_and_updates(
    session: Session,
) -> None:
    service = SourceService(session)

    defaults = service.get_settings()

    assert defaults["joom_browser_provider_url"] == ""
    assert defaults["joom_browser_provider_token"] == ""
    assert defaults["joom_browser_provider_timeout_seconds"] == "25.0"
    assert (
        defaults["joom_browser_provider_wait_selector"] == 'meta[property="product:price:amount"]'
    )

    updated = service.update_settings(
        {
            "joom_browser_provider_url": "https://renderer.example/render",
            "joom_browser_provider_token": "secret-token",
            "joom_browser_provider_timeout_seconds": "12.5",
            "joom_browser_provider_wait_selector": "#price",
        }
    )

    assert updated["joom_browser_provider_url"] == "https://renderer.example/render"
    assert updated["joom_browser_provider_token"] == "secret-token"  # noqa: S105
    assert updated["joom_browser_provider_timeout_seconds"] == "12.5"
    assert updated["joom_browser_provider_wait_selector"] == "#price"


def test_monitor_settings_include_price_refresh_interval_default_and_updates(
    session: Session,
) -> None:
    service = SourceService(session)

    defaults = service.get_settings()

    assert defaults["price_refresh_interval_hours"] == "8"

    updated = service.update_settings({"price_refresh_interval_hours": "12"})

    assert updated["price_refresh_interval_hours"] == "12"


def test_upsert_source_uses_global_refresh_interval_when_source_override_is_missing(
    session: Session,
) -> None:
    service = SourceService(session)

    default_source = service.upsert_source(
        MonitoredSourceInput(
            source_domain="default.test",
            display_name="Default",
            logo_url="https://default.test/logo.png",
            status="active",
            fetch_interval_hours=None,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert default_source.fetch_interval_hours == 8

    coerced_settings = service.update_settings({"price_refresh_interval_hours": "0"})

    assert coerced_settings["price_refresh_interval_hours"] == "1"

    coerced_source = service.upsert_source(
        MonitoredSourceInput(
            source_domain="coerced.test",
            display_name="Coerced",
            logo_url="https://coerced.test/logo.png",
            status="active",
            fetch_interval_hours=None,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert coerced_source.fetch_interval_hours == 1

    service.update_settings({"price_refresh_interval_hours": "12"})

    updated_source = service.upsert_source(
        MonitoredSourceInput(
            source_domain="updated.test",
            display_name="Updated",
            logo_url="https://updated.test/logo.png",
            status="active",
            fetch_interval_hours=None,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert updated_source.fetch_interval_hours == 12

    override_source = service.upsert_source(
        MonitoredSourceInput(
            source_domain="override.test",
            display_name="Override",
            logo_url="https://override.test/logo.png",
            status="active",
            fetch_interval_hours=4,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert override_source.fetch_interval_hours == 4
