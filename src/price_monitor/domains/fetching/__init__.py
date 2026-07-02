from price_monitor.domains.fetching.extraction import extract_product_data
from price_monitor.domains.fetching.ports import (
    FetchedProductData,
    FetchPageResult,
    ProductExtraction,
    ProductPageFetcher,
)
from price_monitor.domains.fetching.service import (
    FetchPipeline,
    ProductFetchResult,
    summarize_price_chart,
)
from price_monitor.domains.fetching.sources.base import (
    FetchContext,
    SourceAdapter,
    SourceFetchResult,
)
from price_monitor.domains.fetching.sources.registry import get_adapter_for_source

__all__ = [
    "FetchContext",
    "FetchPipeline",
    "FetchPageResult",
    "FetchedProductData",
    "ProductExtraction",
    "ProductFetchResult",
    "ProductPageFetcher",
    "SourceAdapter",
    "SourceFetchResult",
    "get_adapter_for_source",
    "extract_product_data",
    "summarize_price_chart",
]
