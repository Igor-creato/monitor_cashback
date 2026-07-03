from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str
    city: str
    stores: list[str] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


SourceType = Literal["admitad", "advcake", "custom", "disabled"]
FallbackBehavior = Literal["status_only", "skip", "custom_api"]


class StoreCreateRequest(BaseModel):
    domain: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    logo_url: str | None = None
    source_type: SourceType = "custom"
    source_config: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    supports_region: bool = False
    fallback_behavior: FallbackBehavior = "status_only"
    active: bool = True

    @field_validator("domain")
    @classmethod
    def normalize_domain_field(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        name = " ".join(value.strip().split())
        if not name:
            raise ValueError("display_name_required")
        return name

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()
        for alias in value:
            normalized = normalize_domain(alias)
            if normalized not in seen:
                aliases.append(normalized)
                seen.add(normalized)
        return aliases

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return normalize_public_image_url(value)


class StoreUpdateRequest(BaseModel):
    display_name: str | None = None
    aliases: list[str] | None = None
    logo_url: str | None = None
    source_type: SourceType | None = None
    source_config: dict[str, Any] | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    supports_region: bool | None = None
    fallback_behavior: FallbackBehavior | None = None
    active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def validate_optional_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return StoreCreateRequest.validate_display_name(value)

    @field_validator("aliases")
    @classmethod
    def normalize_optional_aliases(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return StoreCreateRequest.normalize_aliases(value)

    @field_validator("logo_url")
    @classmethod
    def validate_optional_logo_url(cls, value: str | None) -> str | None:
        return normalize_public_image_url(value)


class ImportStatusResponse(BaseModel):
    source: str
    status: str
    last_started_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    imported_count: int
    skipped_count: int


class StoreResponse(BaseModel):
    id: int
    domain: str
    display_name: str
    active: bool
    source_type: str
    source_config: dict[str, Any]
    aliases: list[str]
    logo_url: str | None
    priority: int
    supports_region: bool
    fallback_behavior: str
    offer_count: int
    import_status: ImportStatusResponse | None
    created_at: datetime | None
    updated_at: datetime | None


class StoreListResponse(BaseModel):
    status: str = "ok"
    items: list[StoreResponse]


_DOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]+)+$")


def normalize_domain(value: str) -> str:
    raw = value.strip().lower()
    if "://" in raw:
        parsed = urlparse(raw)
        raw = parsed.hostname or ""
    raw = raw.removeprefix("www.").strip(".")
    if not raw or "/" in raw or ":" in raw or not _DOMAIN_PATTERN.fullmatch(raw):
        raise ValueError("invalid_domain")
    return raw


def normalize_public_image_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = value.strip()
    if url == "":
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid_logo_url")
    if parsed.username or parsed.password:
        raise ValueError("invalid_logo_url")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("invalid_logo_url")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        raise ValueError("invalid_logo_url")
    return url
