from pydantic import BaseModel, Field

from app.schemas.price_chart import PriceChartTrend
from app.schemas.product_cards import ProductCardCashbackResponse


class WatchlistUiChartSummaryResponse(BaseModel):
    trend: PriceChartTrend
    delta_vs_avg_percent: str | None = None
    headline: str


class WatchlistUiItemResponse(BaseModel):
    subscription_id: int
    tracked_product_id: int
    title: str
    source_display_name: str
    image_url: str | None = None
    current_price: str | None = None
    currency: str | None = None
    availability: bool
    cashback: ProductCardCashbackResponse
    chart_summary: WatchlistUiChartSummaryResponse | None = None


class WatchlistUiPaginationResponse(BaseModel):
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    has_more: bool


class WatchlistUiResponse(BaseModel):
    items: list[WatchlistUiItemResponse]
    pagination: WatchlistUiPaginationResponse
