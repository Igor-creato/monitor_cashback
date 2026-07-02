from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from price_monitor.domains.fetching.ports import ProductExtraction, ProductPageFetcher


@dataclass(frozen=True)
class FetchContext:
    canonical_url: str
    source_domain: str
    source_product_id: str | None
    strategy: str
    fetcher: ProductPageFetcher
    proxy_url: str | None
    fallback_currency: str


@dataclass(frozen=True)
class SourceFetchResult:
    status: str
    extraction: ProductExtraction | None
    http_status: int | None
    response_ms: int | None
    reason: str | None
    block_reason: str | None
    challenge_detected: bool
    parser_version: str | None
    parser_confidence: str | None


class SourceAdapter(Protocol):
    source_domain: str

    def fetch_product(self, context: FetchContext) -> SourceFetchResult:
        ...
