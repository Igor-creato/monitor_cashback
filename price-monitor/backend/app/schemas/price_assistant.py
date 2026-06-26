from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.marketplace_sessions import MarketplaceSessionBundle


class MarketplaceConnectionCreateOnly(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)
    marketplace: str = Field(min_length=1, max_length=64)
    consent_version: str = Field(min_length=1, max_length=191)
    scope: list[str] = Field(min_length=1)
    captured_at: datetime
    connector_version: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class MarketplaceSessionBundleAttach(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)
    consent_version: str = Field(min_length=1, max_length=191)
    scope: list[str] = Field(min_length=1)
    captured_at: datetime
    connector_version: str = Field(min_length=1, max_length=64)
    session_bundle: MarketplaceSessionBundle
    expires_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class OwnerScopedRequest(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)

    model_config = ConfigDict(extra="forbid")


class ReconnectRequiredRequest(OwnerScopedRequest):
    reason: str = Field(min_length=1, max_length=64)


class SyncSessionCreate(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)
    connection_id: int = Field(gt=0)
    collection_type: str = Field(min_length=1, max_length=32)
    started_at: datetime

    model_config = ConfigDict(extra="forbid")


class SyncSessionResponse(BaseModel):
    sync_session_id: int
    connection_id: int
    collection_id: int
    collection_type: str
    source: str
    status: str
    item_count: int
    reason: str | None


class ImportedItemInput(BaseModel):
    external_item_id: str = Field(min_length=1, max_length=191)
    source_product_id: str | None = Field(default=None, max_length=191)
    product_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    quantity: int = Field(default=1, ge=1)
    raw_json: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class SyncItemsRequest(OwnerScopedRequest):
    items: list[ImportedItemInput] = Field(min_length=1, max_length=200)


class SyncItemsResponse(BaseModel):
    sync_session_id: int
    collection_id: int
    upserted_count: int
    item_count: int


class SyncSessionFinish(OwnerScopedRequest):
    status: str = Field(min_length=1, max_length=32)
    reason: str | None = Field(default=None, max_length=64)
    finished_at: datetime


class ImportedItemResponse(BaseModel):
    item_id: int
    external_item_id: str
    source_product_id: str | None
    product_url: str
    title: str | None
    quantity: int


class ImportedCollectionResponse(BaseModel):
    collection_id: int
    collection_type: str
    source: str
    source_display_name: str | None = None
    source_logo_url: str | None = None
    region_code: str
    status: str
    items: list[ImportedItemResponse]


class CollectionsResponse(BaseModel):
    items: list[ImportedCollectionResponse]


class ImportedCollectionDeleteResponse(BaseModel):
    collection_id: int
    status: str


class ProductOfferResponse(BaseModel):
    offer_id: int
    store_code: str
    store_display_name: str
    store_logo_url: str | None = None
    source_code: str
    region_code: str
    product_url: str
    title: str | None
    price: str
    currency: str
    availability: str
    match_confidence: str
    match_label: str
    match_score: int | None = None
    match_status: str | None = None
    match_explanation: dict[str, Any] | None = None
    effective_price: str | None


class ProductCompareResponse(BaseModel):
    tracked_product_id: int
    offers: list[ProductOfferResponse]


class ProductSearchItemResponse(BaseModel):
    store_code: str
    store_display_name: str
    store_logo_url: str | None = None
    source_code: str
    source_display_name: str
    source_logo_url: str | None = None
    title: str | None
    product_url: str | None
    image_url: str | None
    price: str | None
    old_price: str | None
    currency: str | None
    availability: str | None
    match_label: str
    match_score: int | None
    search_url: str | None
    is_fallback: bool


class ProductSearchResponse(BaseModel):
    query: str
    region_code: str
    items: list[ProductSearchItemResponse]
    fallbacks: list[ProductSearchItemResponse]


class AdminStoreCreate(BaseModel):
    store_code: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    homepage_url: str | None = Field(default=None, max_length=2048)
    logo_url: str | None = Field(default=None, max_length=2048)

    model_config = ConfigDict(extra="forbid")


class AdminStorePatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    homepage_url: str | None = Field(default=None, max_length=2048)
    logo_url: str | None = Field(default=None, max_length=2048)

    model_config = ConfigDict(extra="forbid")


class AdminStoreSourceCreate(BaseModel):
    source_code: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    source_type: str = Field(default="feed", max_length=32)
    domains: list[str] = Field(default_factory=list)
    search_template: str | None = Field(default=None, max_length=2048)
    region_support: list[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0, le=1000)
    extraction_mode: str = Field(default="json", max_length=16)
    proxy_tier_policy: str = Field(default="none", max_length=32)
    min_fetch_interval_minutes: int = Field(default=60, ge=1, le=1440)
    matching_threshold: int = Field(default=65, ge=0, le=100)
    cashback_merchant_mapping: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class AdminStoreSourceResponse(BaseModel):
    source_id: int
    source_code: str
    display_name: str
    source_type: str
    enabled: bool
    domains: list[str] = Field(default_factory=list)
    search_template: str | None = None
    region_support: list[str] = Field(default_factory=list)
    priority: int
    extraction_mode: str
    proxy_tier_policy: str
    min_fetch_interval_minutes: int
    matching_threshold: int
    cashback_merchant_mapping: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None


class AdminStoreResponse(BaseModel):
    store_id: int
    store_code: str
    display_name: str
    logo_url: str | None = None
    enabled: bool
    homepage_url: str | None
    sources: list[AdminStoreSourceResponse] = Field(default_factory=list)


class AdminStoresResponse(BaseModel):
    items: list[AdminStoreResponse]


class AdminImportResponse(BaseModel):
    collection_id: int
    site_id: str
    external_user_id: str
    source: str
    region_code: str
    collection_type: str
    status: str
    item_count: int


class AdminImportsResponse(BaseModel):
    items: list[AdminImportResponse]


class AdminDiagnosticsResponse(BaseModel):
    marketplace_connections_total: int
    encrypted_session_secrets_total: int
    imported_collections_total: int
    imported_items_total: int
    stores_total: int
    store_sources_total: int
