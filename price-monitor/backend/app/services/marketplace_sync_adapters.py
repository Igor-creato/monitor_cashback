from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SanitizedMarketplaceItem:
    external_item_id: str
    product_url: str
    source_product_id: str | None = None
    title: str | None = None
    quantity: int = 1
    raw_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class MarketplaceSyncAdapterResult:
    status: str
    items: list[SanitizedMarketplaceItem] = field(default_factory=list)
    reason: str | None = None
    retry_after_seconds: int | None = None

    @classmethod
    def success(
        cls,
        *,
        items: list[SanitizedMarketplaceItem],
    ) -> MarketplaceSyncAdapterResult:
        return cls(status="success", items=items)

    @classmethod
    def partial(
        cls,
        *,
        items: list[SanitizedMarketplaceItem],
        reason: str = "partial_parse",
    ) -> MarketplaceSyncAdapterResult:
        return cls(status="partial", items=items, reason=reason)

    @classmethod
    def failure(
        cls,
        *,
        reason: str,
        retry_after_seconds: int | None = None,
    ) -> MarketplaceSyncAdapterResult:
        return cls(
            status="failure",
            reason=reason,
            retry_after_seconds=retry_after_seconds,
        )


class MarketplaceSyncAdapter(Protocol):
    def fetch_collection(
        self,
        *,
        bundle: dict[str, Any],
        collection_type: str,
    ) -> MarketplaceSyncAdapterResult:
        pass


class AdapterNotConfigured:
    def fetch_collection(
        self,
        *,
        bundle: dict[str, Any],
        collection_type: str,
    ) -> MarketplaceSyncAdapterResult:
        return MarketplaceSyncAdapterResult.failure(reason="adapter_not_configured")


AdapterRegistry = Mapping[tuple[str, str], MarketplaceSyncAdapter]
DEFAULT_ADAPTER_REGISTRY: AdapterRegistry = {}
