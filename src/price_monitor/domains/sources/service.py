from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.core.url_policy import validate_public_product_url
from price_monitor.domains.sources.models import MonitoredSource, MonitorSetting

ALLOWED_SOURCE_STATUSES = {"active", "paused", "disabled"}
DEFAULT_MONITOR_SETTINGS = {"max_tracked_products_per_user": "10"}


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
        normalized_domain = self._normalize_domain(payload.source_domain)
        display_name = payload.display_name.strip()
        logo_url = payload.logo_url.strip()
        status = payload.status.strip().lower()
        if not normalized_domain:
            raise ValueError("source_domain is required")
        if not display_name:
            raise ValueError("display_name is required")
        if not logo_url:
            raise ValueError("logo_url is required")
        if status not in ALLOWED_SOURCE_STATUSES:
            raise ValueError("status is invalid")
        if payload.fetch_interval_hours < 1:
            raise ValueError("fetch_interval_hours must be at least 1")
        if payload.history_retention_days < 1 or payload.history_retention_days > 365:
            raise ValueError("history_retention_days must be between 1 and 365")

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
        validated = validate_public_product_url(raw_url)
        hostname = self._normalize_domain(validated.source_domain)
        active_sources = self._session.scalars(
            select(MonitoredSource).where(MonitoredSource.status == "active")
        ).all()

        matches = [
            source
            for source in active_sources
            if hostname == source.source_domain or hostname.endswith(f".{source.source_domain}")
        ]
        if not matches:
            return None
        return max(matches, key=lambda source: len(source.source_domain))

    def list_sources(self) -> list[MonitoredSource]:
        return self._session.scalars(
            select(MonitoredSource).order_by(MonitoredSource.source_domain)
        ).all()

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

    @staticmethod
    def _normalize_domain(raw_domain: str) -> str:
        return raw_domain.strip().lower().rstrip(".")
