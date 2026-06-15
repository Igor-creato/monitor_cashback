from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MarketplaceSessionValue(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    value: str = Field(min_length=1, max_length=4096)

    model_config = ConfigDict(extra="forbid")


class MarketplaceSessionBundle(BaseModel):
    cookies: list[MarketplaceSessionValue] = Field(default_factory=list)
    tokens: list[MarketplaceSessionValue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class MarketplaceConnectionCreate(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)
    marketplace: str = Field(min_length=1, max_length=64)
    consent_version: str = Field(min_length=1, max_length=191)
    scope: list[str] = Field(min_length=1)
    captured_at: datetime
    connector_version: str = Field(min_length=1, max_length=64)
    session_bundle: MarketplaceSessionBundle | None = None
    expires_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class MarketplaceConnectionStatusResponse(BaseModel):
    connection_id: int
    marketplace: str
    status: str
    last_validated_at: datetime | None
    last_synced_at: datetime | None
    next_retry_at: datetime | None
    reason: str | None


class MarketplaceConnectionsResponse(BaseModel):
    items: list[MarketplaceConnectionStatusResponse]
