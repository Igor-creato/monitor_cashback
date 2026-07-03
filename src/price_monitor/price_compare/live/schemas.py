from __future__ import annotations

from pydantic import BaseModel, Field


class LiveSearchRequest(BaseModel):
    query: str
    city: str
    stores: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=50)
    timeout_seconds: int = Field(default=120, ge=10, le=180)
    mode: str = "live"


class LiveSearchRunResponse(BaseModel):
    status: str
    run_id: str
    poll_url: str


class LiveSearchStatusResponse(BaseModel):
    status: str
    progress: dict[str, object] = Field(default_factory=dict)
    items: list[dict[str, object]] = Field(default_factory=list)
    store_statuses: list[dict[str, object]] = Field(default_factory=list)
    meta: dict[str, object] = Field(default_factory=dict)
