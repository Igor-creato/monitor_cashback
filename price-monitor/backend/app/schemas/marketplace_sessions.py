from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class MarketplaceSessionCookie(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    value: SecretStr = Field(min_length=1, max_length=4096, repr=False)
    domain: str | None = Field(default=None, max_length=255)
    path: str | None = Field(default=None, max_length=255)
    expires: datetime | None = None
    secure: bool | None = None
    httpOnly: bool | None = None
    sameSite: str | None = Field(default=None, max_length=32)

    model_config = ConfigDict(extra="forbid")


class MarketplaceSessionToken(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    value: SecretStr = Field(min_length=1, max_length=4096, repr=False)
    expires: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class MarketplaceSessionBundle(BaseModel):
    cookies: list[MarketplaceSessionCookie] = Field(default_factory=list)
    tokens: list[MarketplaceSessionToken] = Field(default_factory=list)
    captured_at: datetime | None = None
    user_agent_hint: str | None = Field(default=None, max_length=255)
    region_hint: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict, exclude=True)

    model_config = ConfigDict(extra="allow")


class MarketplaceConnectionCreate(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)
    marketplace: str = Field(min_length=1, max_length=64)
    region_code: str | None = Field(default=None, min_length=1, max_length=64)
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
    region_code: str
    status: str
    last_validated_at: datetime | None
    last_synced_at: datetime | None
    next_retry_at: datetime | None
    reason: str | None


class MarketplaceConnectionsResponse(BaseModel):
    items: list[MarketplaceConnectionStatusResponse]
