from typing import Literal

from pydantic import BaseModel

PriceChartTrend = Literal["above_usual", "below_usual", "near_average", "no_data"]
PriceChartGranularity = Literal["raw", "daily"]


class PriceChartSummary(BaseModel):
    current_price: str | None
    avg_price: str | None
    min_price: str | None
    max_price: str | None
    delta_vs_avg_percent: str | None
    trend: PriceChartTrend


class PriceChartPoint(BaseModel):
    ts: str
    price: str


class PriceChartYAxis(BaseModel):
    min: str | None
    avg: str | None
    max: str | None


class PriceChartLabels(BaseModel):
    headline: str


class PriceChartResponse(BaseModel):
    tracked_product_id: int
    title: str
    currency: str
    summary: PriceChartSummary
    series: list[PriceChartPoint]
    y_axis: PriceChartYAxis
    labels: PriceChartLabels
