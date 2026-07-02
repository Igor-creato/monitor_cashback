from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.core.url_policy import validate_public_product_url
from price_monitor.domains.sources.models import MonitoredSource, MonitorSetting

ALLOWED_SOURCE_STATUSES = {"active", "paused", "disabled"}
DEFAULT_PRICE_REFRESH_INTERVAL_HOURS = 8
DEFAULT_MONITOR_SETTINGS = {
    "max_tracked_products_per_user": "10",
    "price_refresh_interval_hours": str(DEFAULT_PRICE_REFRESH_INTERVAL_HOURS),
    "joom_browser_provider_url": "",
    "joom_browser_provider_token": "",
    "joom_browser_provider_timeout_seconds": "25.0",
    "joom_browser_provider_wait_selector": 'meta[property="product:price:amount"]',
}
SECOND_LEVEL_PUBLIC_SUFFIXES = {"ac", "co", "com", "edu", "gov", "mil", "net", "org"}
DOMAIN_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidMonitoredSourceError(ValueError):
    """Raised when monitored source input is invalid."""


@dataclass(frozen=True)
class MonitoredSourceInput:
    source_domain: str
    display_name: str
    logo_url: str
    status: str
    fetch_interval_hours: int
    history_retention_days: int
    browser_fallback_allowed: bool
    proxy_pool_id: str | None


class SourceService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_source(self, payload: MonitoredSourceInput) -> MonitoredSource:
        normalized_domain = normalize_source_domain(payload.source_domain)
        display_name = payload.display_name.strip()
        logo_url = payload.logo_url.strip()
        status = payload.status.strip().lower()
        if not normalized_domain:
            raise InvalidMonitoredSourceError("source_domain is required")
        if not display_name:
            raise InvalidMonitoredSourceError("display_name is required")
        if not logo_url:
            raise InvalidMonitoredSourceError("logo_url is required")
        if status not in ALLOWED_SOURCE_STATUSES:
            raise InvalidMonitoredSourceError("status is invalid")
        if payload.fetch_interval_hours < 1:
            raise InvalidMonitoredSourceError("fetch_interval_hours must be at least 1")
        if payload.history_retention_days < 1 or payload.history_retention_days > 365:
            raise InvalidMonitoredSourceError("history_retention_days must be between 1 and 365")

        source = self._session.get(MonitoredSource, normalized_domain)
        if source is None:
            source = MonitoredSource(source_domain=normalized_domain)

        source.display_name = display_name
        source.logo_url = logo_url
        source.status = status
        source.fetch_interval_hours = payload.fetch_interval_hours
        source.history_retention_days = payload.history_retention_days
        source.browser_fallback_allowed = payload.browser_fallback_allowed
        source.proxy_pool_id = payload.proxy_pool_id
        source.updated_at = datetime.now(UTC)

        self._session.add(source)
        self._session.flush()
        return source

    def find_supported_source(self, raw_url: str) -> MonitoredSource | None:
        source = self.find_source_for_url(raw_url, status="active")
        return source

    def find_source_for_url(
        self, raw_url: str, *, status: str | None = None
    ) -> MonitoredSource | None:
        validated = validate_public_product_url(raw_url)
        hostname = self._normalize_domain(validated.source_domain)
        query = select(MonitoredSource)
        if status is not None:
            query = query.where(MonitoredSource.status == status)
        sources = self._session.scalars(query).all()

        matches = [
            source
            for source in sources
            if hostname == source.source_domain or hostname.endswith(f".{source.source_domain}")
        ]
        if not matches:
            return None
        return max(matches, key=lambda source: len(source.source_domain))

    def list_sources(self) -> list[MonitoredSource]:
        return list(
            self._session.scalars(
                select(MonitoredSource).order_by(MonitoredSource.source_domain)
            ).all()
        )

    def get_settings(self) -> dict[str, str]:
        settings = {
            row.key: row.value
            for row in self._session.scalars(
                select(MonitorSetting).order_by(MonitorSetting.key)
            ).all()
        }
        return {**DEFAULT_MONITOR_SETTINGS, **settings}

    def update_settings(self, values: dict[str, str]) -> dict[str, str]:
        now = datetime.now(UTC)
        for key, value in values.items():
            setting = self._session.get(MonitorSetting, key)
            if setting is None:
                setting = MonitorSetting(key=key, value=value, updated_at=now)
            else:
                setting.value = value
                setting.updated_at = now
            self._session.add(setting)
        self._session.flush()
        return self.get_settings()

    def effective_fetch_interval_hours(self, source: MonitoredSource) -> int:
        if source.fetch_interval_hours >= 1:
            return source.fetch_interval_hours
        return max(1, int(self.get_settings()["price_refresh_interval_hours"]))

    @staticmethod
    def _normalize_domain(raw_domain: str) -> str:
        return raw_domain.strip().lower().rstrip(".")


def normalize_source_domain(raw_domain: str) -> str:
    normalized = raw_domain.strip().lower().rstrip(".")
    if not normalized:
        raise InvalidMonitoredSourceError("source_domain is required")
    if "://" in normalized or any(token in normalized for token in ("/", "?", "#", "@", ":")):
        raise InvalidMonitoredSourceError("source_domain must be a bare domain")

    labels = normalized.split(".")
    if len(labels) < 2:
        raise InvalidMonitoredSourceError("source_domain must be a registrable domain")
    if any(not DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise InvalidMonitoredSourceError("source_domain must be a valid domain")

    top_level_label = labels[-1]
    if len(top_level_label) < 2 or (
        not top_level_label.isalpha() and not top_level_label.startswith("xn--")
    ):
        raise InvalidMonitoredSourceError("source_domain must be a valid domain")

    if len(labels) < 3 and len(top_level_label) == 2 and labels[-2] in SECOND_LEVEL_PUBLIC_SUFFIXES:
        raise InvalidMonitoredSourceError("source_domain must be a registrable domain")

    return normalized
