from datetime import datetime

from pydantic import BaseModel


class ProductCardCashbackResponse(BaseModel):
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


class ProductCardResponse(BaseModel):
    tracked_product_id: int
    subscription_id: int | None = None
    title: str
    image_url: str | None = None
    source: str
    source_display_name: str | None = None
    source_logo_url: str | None = None
    canonical_url: str
    last_price: str | None = None
    last_old_price: str | None = None
    currency: str | None = None
    availability: bool
    last_checked_at: datetime | None = None
    cashback: ProductCardCashbackResponse
