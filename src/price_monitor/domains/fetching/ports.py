from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FetchedProductData:
    title: str
    image_url: str | None
    price_minor: int
    currency: str
    rating_value: str | None


@dataclass(frozen=True)
class FetchPageResult:
    content: str
    final_url: str
    http_status: int
    response_ms: int


class ProductPageFetcher(Protocol):
    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        """Fetch a public product page."""
