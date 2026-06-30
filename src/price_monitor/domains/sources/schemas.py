from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from price_monitor.domains.sources.service import (
    ALLOWED_SOURCE_STATUSES,
    InvalidMonitoredSourceError,
    normalize_source_domain,
)


class MonitoredSourceRequest(BaseModel):
    source_domain: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    logo_url: str = Field(min_length=1, max_length=2048)
    status: str = Field(min_length=1, max_length=32)
    fetch_interval_hours: int = Field(ge=1)
    history_retention_days: int = Field(ge=1, le=365)
    browser_fallback_allowed: bool = False
    proxy_pool_id: str | None = Field(default=None, max_length=36)

    @field_validator("source_domain")
    @classmethod
    def validate_source_domain(cls, value: str) -> str:
        try:
            return normalize_source_domain(value)
        except InvalidMonitoredSourceError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SOURCE_STATUSES:
            raise ValueError("status is invalid")
        return normalized


class MonitoredSourceResponse(BaseModel):
    source_domain: str
    display_name: str
    logo_url: str
    status: str
    fetch_interval_hours: int
    history_retention_days: int
    browser_fallback_allowed: bool
    proxy_pool_id: str | None


class MonitoredSourceListResponse(BaseModel):
    sources: list[MonitoredSourceResponse]


class MonitorSettingsPatchRequest(BaseModel):
    max_tracked_products_per_user: int = Field(ge=1)


class MonitorSettingsResponse(BaseModel):
    settings: dict[str, int]
