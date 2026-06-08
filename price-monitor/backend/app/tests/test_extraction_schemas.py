from decimal import Decimal
from pathlib import Path

import pytest

from app.extraction import (
    ExtractionSchema,
    PriceNotFoundError,
    TitleNotFoundError,
    extract_product_data,
)

testshop_json = {
    "product": {
        "title": "Testshop Phone",
        "price": {
            "current": "$809.70",
            "old": "$899.00",
            "currency": "USD",
        },
        "image": "https://testshop.local/images/phone.jpg",
        "availability": "in_stock",
        "seller": "Testshop",
    }
}

testshop_html = """
<html>
  <body>
    <article class="product">
      <h1 class="product-title">Demo Coat</h1>
      <span class="price">$809.70</span>
      <img class="product-image" src="https://testshop.local/images/coat.jpg" />
    </article>
  </body>
</html>
"""

example_market_html = """
<html>
  <body>
    <main data-source-status="ok">
      <h1 data-testid="title">Example Market Camera</h1>
      <span data-testid="price">809,70 ₽</span>
      <img data-testid="image" src="https://example-market.local/camera.jpg" />
    </main>
  </body>
</html>
"""


def test_testshop_json_extracts_title_price_image() -> None:
    schema = ExtractionSchema(
        source_code="testshop_json",
        version="2026-06-08",
        content_type="json",
        title_path="product.title",
        price_path="product.price.current",
        old_price_path="product.price.old",
        currency_path="product.price.currency",
        image_path="product.image",
        availability_path="product.availability",
        seller_path="product.seller",
        required_fields=["title", "price_current"],
    )

    result = extract_product_data(testshop_json, schema)

    assert result.title == "Testshop Phone"
    assert result.price_current == Decimal("809.70")
    assert result.price_old == Decimal("899.00")
    assert result.currency == "USD"
    assert result.image_url == "https://testshop.local/images/phone.jpg"
    assert result.availability is True
    assert result.seller_name == "Testshop"
    assert result.source_status == "ok"
    assert result.extraction_schema_version == "2026-06-08"


def test_testshop_html_extracts_title_price_image() -> None:
    schema = ExtractionSchema(
        source_code="testshop_html",
        version="1",
        content_type="html",
        css_title=".product-title",
        css_price=".price",
        css_image=".product-image",
        required_fields=["title", "price_current"],
    )

    result = extract_product_data(testshop_html, schema)

    assert result.title == "Demo Coat"
    assert result.price_current == Decimal("809.70")
    assert result.image_url == "https://testshop.local/images/coat.jpg"
    assert result.source_status == "ok"
    assert result.extraction_schema_version == "1"


def test_usd_price_is_normalized_to_decimal() -> None:
    schema = ExtractionSchema(
        source_code="testshop_html",
        version="1",
        content_type="html",
        css_price=".price",
        required_fields=["price_current"],
    )

    result = extract_product_data(testshop_html, schema)

    assert result.price_current == Decimal("809.70")
    assert result.currency == "USD"


def test_rub_price_with_comma_sets_decimal_and_currency() -> None:
    schema = ExtractionSchema(
        source_code="example_market_html",
        version="1",
        content_type="html",
        css_title='[data-testid="title"]',
        css_price='[data-testid="price"]',
        css_image='[data-testid="image"]',
        required_fields=["price_current"],
    )

    result = extract_product_data(example_market_html, schema)

    assert result.title == "Example Market Camera"
    assert result.price_current == Decimal("809.70")
    assert result.currency == "RUB"
    assert result.image_url == "https://example-market.local/camera.jpg"


def test_missing_required_price_raises_price_not_found() -> None:
    schema = ExtractionSchema(
        source_code="testshop_json",
        version="1",
        content_type="json",
        title_path="product.title",
        price_path="product.missing_price",
        required_fields=["price_current"],
    )

    with pytest.raises(PriceNotFoundError):
        extract_product_data(testshop_json, schema)


def test_missing_optional_title_returns_none() -> None:
    schema = ExtractionSchema(
        source_code="testshop_json",
        version="1",
        content_type="json",
        title_path="product.missing_title",
        price_path="product.price.current",
        required_fields=["price_current"],
    )

    result = extract_product_data(testshop_json, schema)

    assert result.title is None
    assert result.price_current == Decimal("809.70")


def test_missing_required_title_raises_title_not_found() -> None:
    schema = ExtractionSchema(
        source_code="testshop_json",
        version="1",
        content_type="json",
        title_path="product.missing_title",
        price_path="product.price.current",
        required_fields=["title", "price_current"],
    )

    with pytest.raises(TitleNotFoundError):
        extract_product_data(testshop_json, schema)


def test_extraction_layer_does_not_import_or_reference_llm() -> None:
    extraction_dir = Path(__file__).resolve().parents[1] / "extraction"
    forbidden_terms = ("llm", "openai", "crawl4ai", "camoufox")

    combined_source = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in extraction_dir.glob("*.py")
    )

    assert not any(term in combined_source for term in forbidden_terms)
