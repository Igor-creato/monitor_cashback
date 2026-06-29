from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from price_monitor.core.url_policy import ValidatedProductUrl


@dataclass(frozen=True)
class ProductMatch:
    product_id: str
    confidence: float


class ProductNormalizer(Protocol):
    def normalize_url(self, raw_url: str) -> ValidatedProductUrl:
        """Normalize and validate a product URL."""


class ProductMatcher(Protocol):
    def match_offer(
        self, *, source_domain: str, title: str, sku: str | None
    ) -> ProductMatch | None:
        """Match an external offer to a service-owned product."""
