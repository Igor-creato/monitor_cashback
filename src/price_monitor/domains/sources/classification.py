from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict
from urllib.parse import urlsplit

from price_monitor.core.url_policy import UnsafeUrlError, validate_public_product_url


@dataclass(frozen=True)
class ProductUrlClassification:
    source_domain: str | None
    canonical_url: str | None
    canonical_url_hash: str | None
    source_product_id: str | None
    is_product_url: bool
    error_code: str | None
    message: str


class StoreRule(TypedDict):
    product_patterns: tuple[re.Pattern[str], ...]
    product_prefixes: tuple[str, ...]
    non_product_prefixes: tuple[str, ...]


STORE_RULES: dict[str, StoreRule] = {
    "aliexpress.com": {
        "product_patterns": (re.compile(r"^/item/(\d+)\.html/?$", re.IGNORECASE),),
        "product_prefixes": ("/item/",),
        "non_product_prefixes": ("/search", "/wholesale", "/category", "/store", "/help"),
    },
    "citilink.ru": {
        "product_patterns": (re.compile(r"^/product/.+-(\d+)/?$", re.IGNORECASE),),
        "product_prefixes": ("/product/",),
        "non_product_prefixes": ("/catalog/", "/search", "/promo", "/specials"),
    },
    "joom.com": {
        "product_patterns": (
            re.compile(r"^/(?:ru/)?products/([A-Za-z0-9_-]+)/?$", re.IGNORECASE),
        ),
        "product_prefixes": ("/products/", "/ru/products/"),
        "non_product_prefixes": ("/search", "/ru/search", "/category", "/collections", "/help"),
    },
    "wildberries.ru": {
        "product_patterns": (
            re.compile(r"^/catalog/(\d+)/detail\.aspx/?$", re.IGNORECASE),
        ),
        "product_prefixes": ("/catalog/",),
        "non_product_prefixes": (
            "/search",
            "/catalog/0/search.aspx",
            "/promo",
            "/brands",
            "/seller",
        ),
    },
    "ozon.ru": {
        "product_patterns": (re.compile(r"^/product/.+?-(\d+)/?$", re.IGNORECASE),),
        "product_prefixes": ("/product/",),
        "non_product_prefixes": ("/category", "/search", "/seller", "/brand"),
    },
    "market.yandex.ru": {
        "product_patterns": (
            re.compile(r"^/(?:product--[^/]+|product|model)/(\d+)(?:/.*)?$", re.IGNORECASE),
        ),
        "product_prefixes": ("/product--", "/product/", "/model/"),
        "non_product_prefixes": ("/search", "/catalog", "/brands", "/comparison"),
    },
}

STABLE_ERROR_MESSAGES = {
    "unsupported_store": "Магазин не поддерживается",
    "not_product_url": "Укажите ссылку на карточку товара.",
    "source_product_id_missing": "Не удалось определить товар по ссылке.",
    "source_url_pattern_unsupported": "Формат ссылки пока не поддерживается.",
}


def classify_product_url(raw_url: str) -> ProductUrlClassification:
    try:
        validated = validate_public_product_url(raw_url)
    except UnsafeUrlError as exc:
        return ProductUrlClassification(
            source_domain=None,
            canonical_url=None,
            canonical_url_hash=None,
            source_product_id=None,
            is_product_url=False,
            error_code="unsafe_url",
            message=str(exc),
        )

    parsed = urlsplit(validated.canonical_url)
    source_domain = _required_store_root(validated.source_domain)
    if source_domain is None:
        return ProductUrlClassification(
            source_domain=validated.source_domain,
            canonical_url=validated.canonical_url,
            canonical_url_hash=validated.canonical_url_hash,
            source_product_id=None,
            is_product_url=False,
            error_code="unsupported_store",
            message=STABLE_ERROR_MESSAGES["unsupported_store"],
        )

    classification = _classify_required_store_url(source_domain, parsed.path)
    if classification is not None:
        return ProductUrlClassification(
            source_domain=source_domain,
            canonical_url=validated.canonical_url,
            canonical_url_hash=validated.canonical_url_hash,
            source_product_id=classification[0],
            is_product_url=classification[1],
            error_code=classification[2],
            message=classification[3],
        )

    return ProductUrlClassification(
        source_domain=source_domain,
        canonical_url=validated.canonical_url,
        canonical_url_hash=validated.canonical_url_hash,
        source_product_id=None,
        is_product_url=False,
        error_code="source_url_pattern_unsupported",
        message=STABLE_ERROR_MESSAGES["source_url_pattern_unsupported"],
    )


def is_required_store_domain(source_domain: str | None) -> bool:
    return source_domain in STORE_RULES


def _classify_required_store_url(
    source_domain: str,
    path: str,
) -> tuple[str | None, bool, str | None, str] | None:
    rules = STORE_RULES[source_domain]
    path_lower = path.lower()
    for pattern in rules["product_patterns"]:
        match = pattern.search(path)
        if match is not None:
            return match.group(1), True, None, ""

    for prefix in rules["non_product_prefixes"]:
        if path_lower.startswith(prefix):
            return None, False, "not_product_url", STABLE_ERROR_MESSAGES["not_product_url"]

    for prefix in rules["product_prefixes"]:
        if path_lower.startswith(prefix):
            return (
                None,
                False,
                "source_product_id_missing",
                STABLE_ERROR_MESSAGES["source_product_id_missing"],
            )

    return None, False, "source_url_pattern_unsupported", STABLE_ERROR_MESSAGES[
        "source_url_pattern_unsupported"
    ]


def _required_store_root(hostname: str) -> str | None:
    for root in STORE_RULES:
        if hostname == root or hostname.endswith(f".{root}"):
            return root
    return None
