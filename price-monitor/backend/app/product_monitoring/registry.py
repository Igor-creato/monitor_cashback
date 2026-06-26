from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

StoreSupportState = Literal["supported", "requires_access", "unsupported"]
StoreFetchStrategy = Literal["structured_data", "official_api", "browser", "none"]


class StoreUrlNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class ProductUrlPattern:
    path_prefix: str
    id_pattern: str | None = None


@dataclass(frozen=True)
class StoreRegistryEntry:
    code: str
    display_name: str
    hostnames: tuple[str, ...]
    support_state: StoreSupportState
    fetch_strategy: StoreFetchStrategy
    url_patterns: tuple[ProductUrlPattern, ...]
    reason: str | None = None


@dataclass(frozen=True)
class StoreUrlNormalization:
    source: str
    external_product_id: str
    canonical_url: str
    region_code: str
    variant_hash: str | None


_TRACKING_QUERY_KEYS = frozenset({"ref", "from", "clid", "gclid", "yclid"})
_SAFE_QUERY_KEYS = frozenset({"region", "variant", "targetUrl"})

_REGISTRY: tuple[StoreRegistryEntry, ...] = (
    StoreRegistryEntry(
        code="wildberries",
        display_name="Wildberries",
        hostnames=("wildberries.ru", "www.wildberries.ru"),
        support_state="supported",
        fetch_strategy="structured_data",
        url_patterns=(ProductUrlPattern("/catalog/", r"^/catalog/([^/]+)/"),),
    ),
    StoreRegistryEntry(
        code="ozon",
        display_name="Ozon",
        hostnames=("ozon.ru", "www.ozon.ru"),
        support_state="supported",
        fetch_strategy="structured_data",
        url_patterns=(ProductUrlPattern("/product/", r"^/product/.+-(\d+)/?$"),),
    ),
    StoreRegistryEntry(
        code="yandex_market",
        display_name="Yandex Market",
        hostnames=("market.yandex.ru",),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"), ProductUrlPattern("/card/")),
        reason="source_requires_access: seller API key is required",
    ),
    StoreRegistryEntry(
        code="dns",
        display_name="DNS",
        hostnames=("dns-shop.ru", "www.dns-shop.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: public data source is not approved",
    ),
    StoreRegistryEntry(
        code="samokat",
        display_name="Samokat",
        hostnames=("samokat.ru", "www.samokat.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: grocery catalog depends on region/session data",
    ),
    StoreRegistryEntry(
        code="vkusvill",
        display_name="VkusVill",
        hostnames=("vkusvill.ru", "www.vkusvill.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/goods/"), ProductUrlPattern("/product/")),
        reason="source_requires_access: regional catalog needs approval",
    ),
    StoreRegistryEntry(
        code="vseinstrumenti",
        display_name="Vseinstrumenti",
        hostnames=("vseinstrumenti.ru", "www.vseinstrumenti.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: official/feed path is not configured",
    ),
    StoreRegistryEntry(
        code="yandex_lavka",
        display_name="Yandex Lavka",
        hostnames=("lavka.yandex.ru",),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: grocery catalog depends on region/session data",
    ),
    StoreRegistryEntry(
        code="goldapple",
        display_name="Gold Apple",
        hostnames=("goldapple.ru", "www.goldapple.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/catalog/"), ProductUrlPattern("/product/")),
        reason="source_requires_access: public data source is not approved",
    ),
    StoreRegistryEntry(
        code="lamoda",
        display_name="Lamoda",
        hostnames=("lamoda.ru", "www.lamoda.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/p/"),),
        reason="source_requires_access: feed/API access needs source approval",
    ),
    StoreRegistryEntry(
        code="etm",
        display_name="ETM",
        hostnames=("etm.ru", "www.etm.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/cat/"), ProductUrlPattern("/product/")),
        reason="source_requires_access: pricing may require account context",
    ),
    StoreRegistryEntry(
        code="pyaterochka",
        display_name="Pyaterochka",
        hostnames=("5ka.ru", "www.5ka.ru", "pyaterochka.ru", "www.pyaterochka.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: grocery catalog depends on region/session data",
    ),
    StoreRegistryEntry(
        code="citilink",
        display_name="Citilink",
        hostnames=("citilink.ru", "www.citilink.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: public data source is not approved",
    ),
    StoreRegistryEntry(
        code="kuper",
        display_name="Kuper",
        hostnames=("kuper.ru", "www.kuper.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: grocery catalog depends on region/session data",
    ),
    StoreRegistryEntry(
        code="yandex_eda",
        display_name="Yandex Eda",
        hostnames=("eda.yandex.ru",),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: data depends on region/session",
    ),
    StoreRegistryEntry(
        code="apteka_ru",
        display_name="Apteka.ru",
        hostnames=("apteka.ru", "www.apteka.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: regional pharmacy data needs approval",
    ),
    StoreRegistryEntry(
        code="mvideo",
        display_name="M.Video",
        hostnames=("mvideo.ru", "www.mvideo.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/products/"), ProductUrlPattern("/product/")),
        reason="source_requires_access: public data source is not approved",
    ),
    StoreRegistryEntry(
        code="petrovich",
        display_name="Petrovich",
        hostnames=("petrovich.ru", "www.petrovich.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"), ProductUrlPattern("/catalog/")),
        reason="source_requires_access: regional catalog needs approval",
    ),
    StoreRegistryEntry(
        code="magnit",
        display_name="Magnit",
        hostnames=("magnit.ru", "www.magnit.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"),),
        reason="source_requires_access: grocery catalog depends on region/session data",
    ),
    StoreRegistryEntry(
        code="lemana_pro",
        display_name="Lemana Pro",
        hostnames=("lemanapro.ru", "www.lemanapro.ru"),
        support_state="requires_access",
        fetch_strategy="none",
        url_patterns=(ProductUrlPattern("/product/"), ProductUrlPattern("/catalog/")),
        reason="source_requires_access: regional catalog needs approval",
    ),
)


def get_store_registry() -> tuple[StoreRegistryEntry, ...]:
    return _REGISTRY


def get_store_entry_by_host(hostname: str) -> StoreRegistryEntry | None:
    normalized = hostname.lower().strip(".")
    for entry in _REGISTRY:
        for allowed_hostname in entry.hostnames:
            if normalized == allowed_hostname or normalized.endswith(
                f".{allowed_hostname}"
            ):
                return entry
    return None


def normalize_store_product_url(url: str) -> StoreUrlNormalization:
    parsed = urlsplit(url)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.scheme != "https" or not hostname:
        raise StoreUrlNormalizationError(
            "unsupported_source: only https URLs are supported"
        )

    entry = get_store_entry_by_host(hostname)
    if entry is None:
        raise StoreUrlNormalizationError("unsupported_source: host is not allowlisted")

    if entry.support_state == "requires_access":
        raise StoreUrlNormalizationError(entry.reason or "source_requires_access")
    if entry.support_state == "unsupported":
        raise StoreUrlNormalizationError(entry.reason or "unsupported_source")

    external_product_id = _extract_external_product_id(parsed.path, entry)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    canonical_query = urlencode(
        [
            (key, value)
            for key, value in query_pairs
            if _is_safe_canonical_query_pair(key)
        ]
    )
    canonical_url = urlunsplit(
        (
            "https",
            hostname,
            parsed.path,
            canonical_query,
            "",
        )
    )
    region_code = _first_non_empty_query_value(query_pairs, "region") or "default"
    variant = _first_non_empty_query_value(query_pairs, "variant")
    variant_hash = (
        hashlib.sha256(variant.encode("utf-8")).hexdigest() if variant else None
    )

    return StoreUrlNormalization(
        source=entry.code,
        external_product_id=external_product_id,
        canonical_url=canonical_url,
        region_code=region_code,
        variant_hash=variant_hash,
    )


def _extract_external_product_id(path: str, entry: StoreRegistryEntry) -> str:
    for pattern in entry.url_patterns:
        if not path.startswith(pattern.path_prefix):
            continue
        if pattern.id_pattern is not None:
            match = re.search(pattern.id_pattern, path)
            if match is not None and match.group(1):
                return match.group(1)
            continue
        path_parts = [part for part in path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[1]:
            return path_parts[1]
    raise StoreUrlNormalizationError("unsupported_source: unsupported product URL path")


def _is_safe_canonical_query_pair(key: str) -> bool:
    normalized_key = key.strip()
    lowered_key = normalized_key.lower()
    if lowered_key.startswith("utm_") or lowered_key in _TRACKING_QUERY_KEYS:
        return False
    return normalized_key in _SAFE_QUERY_KEYS


def _first_non_empty_query_value(
    query_pairs: list[tuple[str, str]],
    key: str,
) -> str | None:
    for query_key, query_value in query_pairs:
        if query_key == key and query_value:
            return query_value
    return None
