from __future__ import annotations

import socket

import pytest

from app.product_monitoring.registry import (
    StoreUrlNormalizationError,
    get_store_entry_by_host,
    get_store_registry,
    normalize_store_product_url,
)

EXPECTED_STORE_CODES = {
    "wildberries",
    "ozon",
    "yandex_market",
    "dns",
    "samokat",
    "vkusvill",
    "vseinstrumenti",
    "yandex_lavka",
    "goldapple",
    "lamoda",
    "etm",
    "pyaterochka",
    "citilink",
    "kuper",
    "yandex_eda",
    "apteka_ru",
    "mvideo",
    "petrovich",
    "magnit",
    "lemana_pro",
}


def test_registry_contains_all_requested_store_codes() -> None:
    entries = get_store_registry()

    assert {entry.code for entry in entries} == EXPECTED_STORE_CODES
    assert len(entries) == len(EXPECTED_STORE_CODES)


def test_registry_entries_have_safe_support_metadata() -> None:
    for entry in get_store_registry():
        assert entry.display_name
        assert entry.hostnames
        assert entry.support_state in {"supported", "requires_access", "unsupported"}
        assert entry.fetch_strategy in {
            "structured_data",
            "official_api",
            "browser",
            "none",
        }
        if entry.support_state != "supported":
            assert entry.reason


def test_host_lookup_supports_subdomains_without_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = 0

    def fail_on_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("registry host lookup must not open network connections")

    monkeypatch.setattr(socket, "create_connection", fail_on_network)

    entry = get_store_entry_by_host("www.wildberries.ru")

    assert entry is not None
    assert entry.code == "wildberries"
    assert network_calls == 0


def test_supported_wildberries_url_normalizes_to_stable_identity() -> None:
    result = normalize_store_product_url(
        "https://www.wildberries.ru/catalog/123456/detail.aspx"
        "?utm_source=ad&ref=partner&targetUrl=EX"
    )

    assert result.source == "wildberries"
    assert result.external_product_id == "123456"
    assert (
        result.canonical_url
        == "https://www.wildberries.ru/catalog/123456/detail.aspx?targetUrl=EX"
    )
    assert result.region_code == "default"
    assert result.variant_hash is None


def test_supported_ozon_url_normalizes_to_numeric_sku_identity() -> None:
    result = normalize_store_product_url(
        "https://www.ozon.ru/product/smartfon-test-123456789/"
        "?utm_source=ad&from=share&region=msk"
    )

    assert result.source == "ozon"
    assert result.external_product_id == "123456789"
    assert (
        result.canonical_url
        == "https://www.ozon.ru/product/smartfon-test-123456789/?region=msk"
    )
    assert result.region_code == "msk"
    assert result.variant_hash is None


def test_ozon_url_without_numeric_sku_fails_closed() -> None:
    with pytest.raises(StoreUrlNormalizationError, match="unsupported_source"):
        normalize_store_product_url("https://www.ozon.ru/product/test-product/")


def test_unknown_store_fails_closed_with_safe_reason() -> None:
    with pytest.raises(StoreUrlNormalizationError, match="unsupported_source"):
        normalize_store_product_url("https://unknown-shop.example/product/123")
