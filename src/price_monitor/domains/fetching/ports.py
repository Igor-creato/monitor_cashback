from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class FetchedProductData:
    title: str
    image_url: str | None
    price_minor: int
    currency: str
    rating_value: str | None


@dataclass(frozen=True)
class ProductExtraction:
    title: str
    price_minor: int
    currency: str
    image_url: str | None
    rating_value: str | None
    availability: str | None
    canonical_url: str
    source_product_id: str | None
    parser_version: str
    confidence: Decimal


@dataclass(frozen=True)
class FetchPageResult:
    content: str
    final_url: str
    http_status: int
    response_ms: int


class ProductPageFetcher(Protocol):
    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        """Fetch a public product page."""


class ProxyUrlResolver(Protocol):
    def resolve(self, *, secret_ref: str) -> str | None:
        """Resolve a proxy secret reference into a usable proxy URL."""
