from datetime import datetime

from pydantic import BaseModel


class ProductPriceHistoryPoint(BaseModel):
    price_current: str
    price_old: str | None
    currency: str
    availability: bool
    fetched_at: datetime


class ProductPriceHistoryResponse(BaseModel):
    points: list[ProductPriceHistoryPoint]
