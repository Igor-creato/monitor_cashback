import pytest

from price_monitor.domains.sources.classification import (
    classify_product_url,
    is_required_store_domain,
)


@pytest.mark.parametrize(
    ("url", "domain", "source_product_id"),
    (
        (
            "https://www.aliexpress.com/item/1005001112223334.html",
            "aliexpress.com",
            "1005001112223334",
        ),
        (
            "https://aliexpress.ru/item/1005001112223334.html",
            "aliexpress.ru",
            "1005001112223334",
        ),
        ("https://www.citilink.ru/product/router-wifi-123456/", "citilink.ru", "123456"),
        (
            "https://www.joom.com/ru/products/64f1abcd1234567890abcdef",
            "joom.com",
            "64f1abcd1234567890abcdef",
        ),
        (
            "https://www.wildberries.ru/catalog/123456789/detail.aspx",
            "wildberries.ru",
            "123456789",
        ),
        ("https://www.ozon.ru/product/example-123456789/", "ozon.ru", "123456789"),
        (
            "https://market.yandex.ru/product--phone/123456789",
            "market.yandex.ru",
            "123456789",
        ),
    ),
)
def test_required_store_product_urls_are_classified(
    url: str,
    domain: str,
    source_product_id: str,
) -> None:
    result = classify_product_url(url)

    assert result.is_product_url is True
    assert result.source_domain == domain
    assert result.source_product_id == source_product_id
    assert result.error_code is None


@pytest.mark.parametrize(
    ("url", "error_code"),
    (
        ("https://www.aliexpress.com/wholesale?SearchText=phone", "not_product_url"),
        ("https://aliexpress.ru/wholesale?SearchText=phone", "not_product_url"),
        ("https://www.citilink.ru/catalog/smartfony/", "not_product_url"),
        ("https://www.joom.com/ru/search/q.phone", "not_product_url"),
        ("https://www.wildberries.ru/catalog/0/search.aspx?search=phone", "not_product_url"),
        ("https://www.ozon.ru/category/smartfony-15502/", "not_product_url"),
        ("https://market.yandex.ru/search?text=phone", "not_product_url"),
        ("https://www.ozon.ru/product/example-/", "source_product_id_missing"),
        ("https://www.aliexpress.com/p/1005001112223334", "source_url_pattern_unsupported"),
        ("https://example.com/p/1", "unsupported_store"),
        ("http://127.0.0.1/product/1", "unsafe_url"),
    ),
)
def test_non_product_and_unsafe_urls_get_stable_errors(
    url: str,
    error_code: str,
) -> None:
    result = classify_product_url(url)

    assert result.is_product_url is False
    assert result.error_code == error_code


@pytest.mark.parametrize(
    ("source_domain", "expected"),
    (
        ("aliexpress.com", True),
        ("aliexpress.ru", True),
        ("shop.ozon.ru", False),
        ("example.com", False),
        (None, False),
    ),
)
def test_required_store_domain_detection(source_domain: str | None, expected: bool) -> None:
    assert is_required_store_domain(source_domain) is expected
