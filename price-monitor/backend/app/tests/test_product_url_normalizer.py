import hashlib
import socket

import pytest

from app.core.product_url_normalizer import (
    UnsupportedSourceError,
    normalize_product_url,
)


def test_removes_utm_parameters_from_canonical_url() -> None:
    result = normalize_product_url(
        "https://testshop.local/product/123?utm_source=x&utm_campaign=summer"
    )

    assert result.canonical_url == "https://testshop.local/product/123"


def test_removes_ref_parameter_from_canonical_url() -> None:
    result = normalize_product_url(
        "https://example-market.local/item/abc-777?ref=partner&region=msk"
    )

    assert (
        result.canonical_url
        == "https://example-market.local/item/abc-777?region=msk"
    )


@pytest.mark.parametrize(
    ("url", "source", "external_product_id"),
    [
        ("https://testshop.local/product/123", "testshop", "123"),
        ("https://example-market.local/item/abc-777", "example_market", "abc-777"),
        ("https://demo-store.local/goods/sku-42", "demo_store", "sku-42"),
    ],
)
def test_extracts_product_id_for_supported_sources(
    url: str,
    source: str,
    external_product_id: str,
) -> None:
    result = normalize_product_url(url)

    assert result.source == source
    assert result.external_product_id == external_product_id


def test_extracts_region_from_query() -> None:
    result = normalize_product_url(
        "https://example-market.local/item/abc-777?region=msk"
    )

    assert result.region_code == "msk"


def test_defaults_region_to_default_when_missing() -> None:
    result = normalize_product_url("https://testshop.local/product/123")

    assert result.region_code == "default"


def test_creates_variant_hash_only_when_variant_is_present() -> None:
    without_variant = normalize_product_url("https://testshop.local/product/123")
    with_variant = normalize_product_url(
        "https://testshop.local/product/123?variant=blue-xl"
    )

    assert without_variant.variant_hash is None
    assert with_variant.variant_hash == hashlib.sha256(b"blue-xl").hexdigest()


def test_rejects_unknown_domain_with_unsupported_source_error() -> None:
    with pytest.raises(UnsupportedSourceError):
        normalize_product_url("https://unknown.local/product/123")


def test_normalization_does_not_make_network_requests(monkeypatch) -> None:
    network_calls = 0

    def fail_on_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("normalizer must not open network connections")

    monkeypatch.setattr(socket, "create_connection", fail_on_network)

    normalize_product_url("https://testshop.local/product/123?utm_source=x")
    normalize_product_url(
        "https://example-market.local/item/abc-777?ref=partner&region=msk"
    )
    with pytest.raises(UnsupportedSourceError):
        normalize_product_url("https://unknown.local/product/123")

    assert network_calls == 0
