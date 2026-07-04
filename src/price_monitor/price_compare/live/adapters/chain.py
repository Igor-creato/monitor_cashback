from __future__ import annotations

from collections.abc import Sequence

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    STORE_STATUS_OK,
    LiveSearchQuery,
    LiveStoreResult,
    SearchAdapter,
)
from price_monitor.price_compare.schemas import normalize_domain


class ProviderChainSearchAdapter:
    def __init__(self, *, domain: str, providers: Sequence[SearchAdapter]) -> None:
        self._domain = normalize_domain(domain)
        self._providers = tuple(providers)

    @property
    def providers(self) -> tuple[SearchAdapter, ...]:
        return self._providers

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        warnings: list[str] = []
        last_result: LiveStoreResult | None = None
        for provider in self._providers:
            try:
                result = provider.search(query)
            except Exception:
                result = LiveStoreResult(
                    store_domain=self._domain,
                    status=STORE_STATUS_FAILED,
                    items=[],
                    warnings=["provider_chain_provider_failed"],
                    message="Провайдер поиска не смог получить страницу магазина",
                )
            if result.status == STORE_STATUS_BLOCKED_BY_ANTIBOT:
                return result
            if result.status == STORE_STATUS_OK and result.items:
                return result
            last_result = result
            warnings.extend(result.warnings)
            if result.status == STORE_STATUS_OK:
                warnings.append("provider_returned_no_items")

        if last_result is None:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["provider_chain_empty"],
                message="Провайдеры поиска не настроены",
            )

        return LiveStoreResult(
            store_domain=self._domain,
            status=STORE_STATUS_FAILED,
            items=[],
            warnings=_dedupe(warnings),
            message=last_result.message or "Провайдеры поиска не смогли получить товары",
        )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
