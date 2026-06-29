"""Import all SQLAlchemy models for metadata registration."""

from price_monitor.domains.pricing.models import PricePoint
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import (
    FetchJob,
    IdempotencyRecord,
    InboxMessage,
    OutboxEvent,
)
from price_monitor.domains.sources.models import SourceStatus
from price_monitor.domains.watchlist.models import WatchlistItem

__all__ = [
    "FetchJob",
    "IdempotencyRecord",
    "InboxMessage",
    "OutboxEvent",
    "PricePoint",
    "Product",
    "SourceStatus",
    "WatchlistItem",
]
