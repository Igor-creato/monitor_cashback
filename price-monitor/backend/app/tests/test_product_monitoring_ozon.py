from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.fetchers.base import FetchError
from app.product_monitoring.ozon import parse_ozon_public_page

FETCHED_AT = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


def test_parse_ozon_public_page_extracts_product_data_from_json_ld() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
          {
            "@type": "Product",
            "name": "Ozon Phone 256GB",
            "image": ["https://cdn.ozon.example/phone.jpg"],
            "offers": {
              "@type": "Offer",
              "price": "24999.90",
              "priceCurrency": "RUB",
              "availability": "https://schema.org/InStock",
              "seller": {"name": "Ozon"}
            }
          }
        </script>
      </head>
    </html>
    """

    result = parse_ozon_public_page(html, fetched_at=FETCHED_AT)

    assert result.product_name == "Ozon Phone 256GB"
    assert result.price_current == Decimal("24999.90")
    assert result.price_old is None
    assert result.currency == "RUB"
    assert result.availability is True
    assert result.seller_name == "Ozon"
    assert result.image_url == "https://cdn.ozon.example/phone.jpg"
    assert result.fetched_at == FETCHED_AT


def test_parse_ozon_public_page_extracts_sale_price_and_old_price() -> None:
    html = """
    <html>
      <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Ozon Sale Product",
          "offers": {
            "price": "1990",
            "priceCurrency": "RUB",
            "priceSpecification": {
              "price": "2490",
              "priceCurrency": "RUB"
            }
          }
        }
      </script>
    </html>
    """

    result = parse_ozon_public_page(html, fetched_at=FETCHED_AT)

    assert result.price_current == Decimal("1990.00")
    assert result.price_old == Decimal("2490.00")


@pytest.mark.parametrize(
    "html",
    [
        "<html><title>Доступ ограничен</title><body>captcha</body></html>",
        "<html><body>login_required</body></html>",
    ],
)
def test_parse_ozon_public_page_detects_captcha_or_login_required(html: str) -> None:
    with pytest.raises(FetchError) as exc_info:
        parse_ozon_public_page(html, fetched_at=FETCHED_AT)

    assert exc_info.value.error_type == "captcha_detected"


def test_parse_ozon_public_page_fails_closed_when_price_is_missing() -> None:
    html = """
    <html>
      <script type="application/ld+json">
        {"@type": "Product", "name": "Ozon Product Without Price"}
      </script>
    </html>
    """

    with pytest.raises(FetchError) as exc_info:
        parse_ozon_public_page(html, fetched_at=FETCHED_AT)

    assert exc_info.value.error_type == "price_not_found"
