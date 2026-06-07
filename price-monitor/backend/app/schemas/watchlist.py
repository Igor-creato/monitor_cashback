from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


class WatchlistItemsResponse(BaseModel):
    items: list[WatchlistItemResponse]
    limit: int = Field(ge=1, le=100)
