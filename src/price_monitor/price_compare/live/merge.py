from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_OK,
    LiveSearchItem,
    LiveStoreResult,
)
from price_monitor.price_compare.search import AVAILABILITY_SORT_RANK

_TOKEN_PATTERN = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_STOPWORDS = {
    "в",
    "и",
    "на",
    "по",
    "с",
    "для",
    "под",
    "от",
    "из",
    "the",
    "a",
    "an",
}
_ACCESSORY_TERMS = (
    "чехол",
    "кабель",
    "пульт",
    "кронштейн",
    "защитное стекло",
    "аккумулятор",
    "запчасть",
)


def merge_live_results(
    results: list[LiveStoreResult], query: str, limit: int
) -> list[LiveSearchItem]:
    items: list[LiveSearchItem] = []
    seen_urls: set[str] = set()
    for result in results:
        if result.status != STORE_STATUS_OK:
            continue
        for item in result.items:
            relevant, reason = classify_relevance(query, item)
            if not relevant:
                continue
            dedupe_key = item.url.strip().lower()
            if dedupe_key and dedupe_key in seen_urls:
                continue
            if dedupe_key:
                seen_urls.add(dedupe_key)
            store_domain = item.store_domain or result.store_domain
            items.append(
                replace(
                    item,
                    store_domain=store_domain,
                    store_name=item.store_name or store_domain,
                    relevance_reason=reason,
                )
            )
    return sorted(items, key=_sort_key)[:limit]


def classify_relevance(query: str, item: LiveSearchItem) -> tuple[bool, str]:
    query_tokens = _meaningful_tokens(query)
    haystack = _normalize_text(" ".join([item.title, item.category or ""]))
    missing_tokens = [token for token in query_tokens if token not in haystack]
    if missing_tokens:
        return False, "missing_query_tokens"

    query_text = _normalize_text(query)
    for term in _ACCESSORY_TERMS:
        if term in haystack and term not in query_text:
            return False, "accessory_term"

    return True, "query_tokens_matched"


def _sort_key(item: LiveSearchItem) -> tuple[int, Decimal, str, str]:
    price = item.price if isinstance(item.price, Decimal) else None
    if price is None and item.price is not None:
        price = Decimal(str(item.price))
    return (
        AVAILABILITY_SORT_RANK.get(item.availability, AVAILABILITY_SORT_RANK["unknown"]),
        price if price is not None else Decimal("Infinity"),
        item.store_domain,
        item.title,
    )


def _meaningful_tokens(value: str) -> list[str]:
    return [token for token in _tokens(value) if token not in _STOPWORDS]


def _tokens(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value.lower().replace("ё", "е"))


def _normalize_text(value: str) -> str:
    return " ".join(_tokens(value))
