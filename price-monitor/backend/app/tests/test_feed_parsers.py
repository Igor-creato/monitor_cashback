from __future__ import annotations

import pytest

from app.feeds.parsers import (
    UnsupportedFeedFormatError,
    parse_csv,
    parse_feed,
    parse_json,
    parse_xml,
    parse_yaml,
)

CSV_FIXTURE = (
    "product_id,title,url,price,old_price,currency,category_id,image_url,availability\n"
    "ext-1,Demo Product,https://testshop.example/product/1,1990.00,2490.00,RUB,cat-1,"
    "https://testshop.example/img/1.jpg,in stock\n"
)

JSON_LIST_FIXTURE = """
[
  {
    "product_id": "ext-1",
    "title": "Demo Product",
    "url": "https://testshop.example/product/1",
    "price": "1990.00",
    "old_price": "2490.00",
    "currency": "RUB",
    "category_id": "cat-1",
    "image_url": "https://testshop.example/img/1.jpg",
    "availability": "in stock"
  }
]
"""

JSON_WRAPPED_FIXTURE = """
{
  "items": [
    {
      "product_id": "ext-2",
      "title": "Second Product",
      "url": "https://testshop.example/product/2",
      "price": "500.00",
      "currency": "RUB",
      "availability": "in stock"
    }
  ]
}
"""

YAML_FIXTURE = """
- product_id: ext-1
  title: Demo Product
  url: https://testshop.example/product/1
  price: "1990.00"
  old_price: "2490.00"
  currency: RUB
  category_id: cat-1
  image_url: https://testshop.example/img/1.jpg
  availability: in stock
"""

XML_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog>
  <shop>
    <offers>
      <offer id="ext-1">
        <url>https://testshop.example/product/1</url>
        <price>1990.00</price>
        <oldprice>2490.00</oldprice>
        <name>Demo Product</name>
        <picture>https://testshop.example/img/1.jpg</picture>
        <categoryId>cat-1</categoryId>
        <available>true</available>
      </offer>
    </offers>
  </shop>
</yml_catalog>
"""


def test_parse_csv_fixture() -> None:
    records = parse_csv(CSV_FIXTURE)

    assert len(records) == 1
    record = records[0]
    assert record["product_id"] == "ext-1"
    assert record["url"] == "https://testshop.example/product/1"
    assert record["price"] == "1990.00"
    assert record["availability"] == "in stock"


def test_parse_json_list_fixture() -> None:
    records = parse_json(JSON_LIST_FIXTURE)

    assert len(records) == 1
    assert records[0]["product_id"] == "ext-1"
    assert records[0]["url"] == "https://testshop.example/product/1"


def test_parse_json_wrapped_fixture() -> None:
    records = parse_json(JSON_WRAPPED_FIXTURE)

    assert len(records) == 1
    assert records[0]["product_id"] == "ext-2"
    assert records[0]["price"] == "500.00"


def test_parse_yaml_fixture() -> None:
    records = parse_yaml(YAML_FIXTURE)

    assert len(records) == 1
    assert records[0]["product_id"] == "ext-1"
    assert records[0]["title"] == "Demo Product"
    assert records[0]["currency"] == "RUB"


def test_parse_xml_fixture() -> None:
    records = parse_xml(XML_FIXTURE)

    assert len(records) == 1
    record = records[0]
    assert record["product_id"] == "ext-1"
    assert record["url"] == "https://testshop.example/product/1"
    assert record["price"] == "1990.00"
    assert record["old_price"] == "2490.00"
    assert record["title"] == "Demo Product"
    assert record["image_url"] == "https://testshop.example/img/1.jpg"
    assert record["category_id"] == "cat-1"
    assert record["availability"] == "true"


def test_fields_mapping_renames_keys() -> None:
    raw_csv = (
        "id,name,link,cost\n"
        "ext-9,Mapped Product,https://testshop.example/product/9,777.00\n"
    )
    mapping = {"id": "product_id", "name": "title", "link": "url", "cost": "price"}

    records = parse_csv(raw_csv, fields_mapping=mapping)

    assert records[0]["product_id"] == "ext-9"
    assert records[0]["title"] == "Mapped Product"
    assert records[0]["url"] == "https://testshop.example/product/9"
    assert records[0]["price"] == "777.00"
    # Original keys must be gone after mapping.
    assert "name" not in records[0]
    assert "link" not in records[0]


def test_parse_feed_dispatches_by_format() -> None:
    assert parse_feed(CSV_FIXTURE, "csv")[0]["product_id"] == "ext-1"
    assert parse_feed(JSON_LIST_FIXTURE, "json")[0]["product_id"] == "ext-1"
    assert parse_feed(YAML_FIXTURE, "yaml")[0]["product_id"] == "ext-1"
    assert parse_feed(YAML_FIXTURE, "yml")[0]["product_id"] == "ext-1"
    assert parse_feed(XML_FIXTURE, "xml")[0]["product_id"] == "ext-1"


def test_parse_feed_unknown_format_raises() -> None:
    with pytest.raises(UnsupportedFeedFormatError):
        parse_feed(CSV_FIXTURE, "toml")
