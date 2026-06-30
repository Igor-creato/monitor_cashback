"""Import all SQLAlchemy models for metadata registration."""

from price_monitor.domains.pricing.models import PricePoint
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import (
    AlertEvent,
    FetchAttempt,
    FetchJob,
    IdempotencyRecord,
    InboxMessage,
    OutboxEvent,
)
from price_monitor.domains.sources.models import (
    MonitoredSource,
    MonitorSetting,
    ProxyEndpoint,
    ProxyPool,
    SourceStatus,
)
from price_monitor.domains.watchlist.models import WatchlistItem

__all__ = [
    "AlertEvent",
    "FetchAttempt",
    "FetchJob",
    "IdempotencyRecord",
    "InboxMessage",
    "MonitorSetting",
    "MonitoredSource",
    "OutboxEvent",
    "PricePoint",
    "Product",
    "ProxyEndpoint",
    "ProxyPool",
    "SourceStatus",
    "WatchlistItem",
]
