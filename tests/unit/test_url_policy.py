import pytest

from price_monitor.core.url_policy import UnsafeUrlError, validate_public_product_url


def test_normalizes_supported_product_url_and_hashes_canonical_form() -> None:
    result = validate_public_product_url(
        "HTTPS://Example.COM:443/store/item?id=42&utm_source=newsletter#reviews"
    )

    assert result.canonical_url == "https://example.com/store/item?id=42"
    assert result.source_domain == "example.com"
    assert len(result.canonical_url_hash) == 64


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/item",
        "https://localhost/item",
        "https://127.0.0.1/item",
        "https://10.1.2.3/item",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/item",
        "https://internal/item",
    ],
)
def test_rejects_urls_that_can_reach_private_or_local_networks(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_product_url(url)
