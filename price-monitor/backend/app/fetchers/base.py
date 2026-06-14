from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

FetchErrorType = Literal[
    "http_403",
    "http_429",
    "timeout",
    "parser_error",
    "price_not_found",
    "bad_content",
    "source_unavailable",
]


@dataclass(frozen=True)
class PriceFetchResult:
    product_name: str | None
    price_current: Decimal
    price_old: Decimal | None
    currency: str
    availability: bool
    seller_name: str | None
    image_url: str | None
    fetched_at: datetime


@dataclass(frozen=True)
class FetchedPage:
    content: dict | str | bytes
    content_type: str
    fetched_at: datetime
    http_status: int | None = None
    response_ms: int | None = None
    bytes_downloaded: int | None = None


class FetchError(Exception):
    def __init__(self, error_type: FetchErrorType, message: str | None = None) -> None:
        self.error_type = error_type
        super().__init__(message or error_type)
