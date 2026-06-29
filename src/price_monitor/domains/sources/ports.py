from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProductFetchResult:
    source_domain: str
    canonical_url: str
    title: str | None
    price_minor: int | None
    currency: str | None
    availability: str


class ProductSourceAdapter(Protocol):
    def fetch_product(self, canonical_url: str) -> ProductFetchResult:
        """Fetch a public product URL through a source-specific adapter."""
