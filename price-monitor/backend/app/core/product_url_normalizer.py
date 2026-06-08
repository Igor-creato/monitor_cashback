from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class NormalizedProductUrl:
    source: str
    external_product_id: str
    canonical_url: str
    region_code: str
    variant_hash: str | None


class UnsupportedSourceError(ValueError):
    pass


_SOURCE_CONFIG = {
    "testshop.local": ("testshop", "product"),
    "example-market.local": ("example_market", "item"),
    "demo-store.local": ("demo_store", "goods"),
}


def normalize_product_url(url: str) -> NormalizedProductUrl:
    parsed = urlsplit(url)
    hostname = parsed.hostname.lower() if parsed.hostname else ""

    if parsed.scheme != "https" or hostname not in _SOURCE_CONFIG:
        raise UnsupportedSourceError("unsupported product URL source")

    source, expected_prefix = _SOURCE_CONFIG[hostname]
    path_parts = [part for part in parsed.path.split("/") if part]

    if len(path_parts) < 2 or path_parts[0] != expected_prefix or not path_parts[1]:
        raise UnsupportedSourceError("unsupported product URL path")

    external_product_id = path_parts[1]
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    canonical_query_pairs = [
        (key, value) for key, value in query_pairs if not _is_tracking_query_key(key)
    ]
    canonical_query = urlencode(canonical_query_pairs)
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

    return NormalizedProductUrl(
        source=source,
        external_product_id=external_product_id,
        canonical_url=canonical_url,
        region_code=region_code,
        variant_hash=variant_hash,
    )


def _is_tracking_query_key(key: str) -> bool:
    normalized_key = key.lower()
    return normalized_key == "ref" or normalized_key.startswith("utm_")


def _first_non_empty_query_value(
    query_pairs: list[tuple[str, str]],
    key: str,
) -> str | None:
    for query_key, query_value in query_pairs:
        if query_key == key and query_value:
            return query_value
    return None
