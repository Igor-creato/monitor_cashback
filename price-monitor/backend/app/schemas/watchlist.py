from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.product_cards import ProductCardCashbackResponse


class WatchlistItemCreate(BaseModel):
    site_id: str
    external_user_id: str
    product_url: str
    target_price: Decimal | None = None
    target_effective_price: Decimal | None = None
    region_code: str = "default"


class WatchlistItemPatch(BaseModel):
    target_price: Decimal | None = None
    target_effective_price: Decimal | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="ignore")


class WatchlistCashbackLinkRequest(BaseModel):
    site_id: str
    external_user_id: str


class WatchlistCashbackLinkResponse(BaseModel):
    cashback_url: str
    link_type: str
    cashback_status: str


class WatchlistItemResponse(BaseModel):
    subscription_id: int
    tracked_product_id: int
    site_id: str
    external_user_id: str
    product_url: str
    source: str
    external_product_id: str
    region_code: str
    target_price: str | None
    target_effective_price: str | None
    is_active: bool


class WatchlistItemCreateResponse(WatchlistItemResponse):
    result: Literal["created", "already_exists"]


class WatchlistItemCashbackResponse(BaseModel):
    cashback_status: str
    cashback_available: bool
    merchant_id: str | None = None
    merchant_name: str | None = None
    network: str | None = None
    offer_id: str | None = None
    user_cashback_exact_rate: str | None = None
    user_cashback_min_rate: str | None = None
    user_cashback_max_rate: str | None = None
    expected_cashback_exact: str | None = None
    expected_cashback_min: str | None = None
    expected_cashback_max: str | None = None
    effective_price: str | None = None
    effective_price_conservative: str | None = None
    confidence: str | None = None
    display_policy: str
    message: str | None = None


class WatchlistItemWithCashbackResponse(WatchlistItemResponse):
    title: str
    image_url: str | None = None
    source_display_name: str | None = None
    canonical_url: str
    last_price: str | None = None
    last_old_price: str | None = None
    currency: str | None = None
    availability: bool
    last_checked_at: datetime | None = None
    cashback: ProductCardCashbackResponse


class WatchlistItemsResponse(BaseModel):
    items: list[WatchlistItemWithCashbackResponse]
    limit: int = Field(ge=1, le=100)
