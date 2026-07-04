from decimal import Decimal

from price_monitor.price_compare.feed_parsers import (
    parse_admitad_csv_feed,
    parse_admitad_xml_feed,
    parse_advcake_yml_feed,
)


def test_parse_admitad_csv_feed_maps_product_rows_without_secret_values() -> None:
    csv_payload = (
        "id;title;url;price;currency;picture;category;brand;availability\n"
        "sku-1; Redmi Note 13 ;https://shop.test/product/1;12990,50;rub;"
        "https://img.test/1.jpg;Смартфоны;Xiaomi;available\n"
    )

    offers = list(
        parse_admitad_csv_feed(
            csv_payload.encode("utf-8"),
            store_domain="shop.test",
            source="admitad_product_feed",
        )
    )

    assert len(offers) == 1
    assert offers[0].external_id == "sku-1"
    assert offers[0].title == "Redmi Note 13"
    assert offers[0].url == "https://shop.test/product/1"
    assert offers[0].price == Decimal("12990.50")
    assert offers[0].currency == "RUB"
    assert offers[0].image_url == "https://img.test/1.jpg"
    assert offers[0].category == "Смартфоны"
    assert offers[0].brand == "Xiaomi"
    assert "secret" not in repr(offers[0]).lower()


def test_parse_admitad_xml_feed_maps_required_product_fields() -> None:
    xml_payload = b"""<?xml version="1.0" encoding="UTF-8"?>
    <products>
      <product>
        <id>sku-2</id>
        <name>Apple iPhone 15</name>
        <url>https://store.test/iphone-15</url>
        <price>79990</price>
        <currency>RUB</currency>
        <image>https://img.test/iphone.jpg</image>
        <category>Phones</category>
        <brand>Apple</brand>
        <available>true</available>
      </product>
    </products>
    """

    offers = list(parse_admitad_xml_feed(xml_payload, store_domain="store.test"))

    assert len(offers) == 1
    assert offers[0].external_id == "sku-2"
    assert offers[0].title == "Apple iPhone 15"
    assert offers[0].price == Decimal("79990")
    assert offers[0].availability == "in_stock"
    assert offers[0].source == "admitad_product_feed"


def test_parse_advcake_yml_feed_treats_always_true_available_as_unknown() -> None:
    yml_payload = b"""<?xml version="1.0" encoding="UTF-8"?>
    <yml_catalog date="2026-07-04 12:00">
      <shop>
        <offers>
          <offer id="offer-1" available="true">
            <url>https://merchant.test/catalog/redmi</url>
            <name>Redmi Note 13 NFC</name>
            <vendor>Xiaomi</vendor>
            <model>Note 13</model>
            <categoryId>10</categoryId>
            <price>15990</price>
            <oldprice>17990</oldprice>
            <currencyId>RUB</currencyId>
            <picture>https://img.test/redmi.jpg</picture>
            <barcode>4600000000001</barcode>
            <param name="memory">256GB</param>
          </offer>
        </offers>
      </shop>
    </yml_catalog>
    """

    offers = list(parse_advcake_yml_feed(yml_payload, store_domain="merchant.test"))

    assert len(offers) == 1
    assert offers[0].source == "advcake_product_feed"
    assert offers[0].external_id == "offer-1"
    assert offers[0].title == "Redmi Note 13 NFC"
    assert offers[0].brand == "Xiaomi"
    assert offers[0].price == Decimal("15990")
    assert offers[0].currency == "RUB"
    assert offers[0].availability == "unknown"
    assert offers[0].image_url == "https://img.test/redmi.jpg"


def test_parse_advcake_yml_feed_skips_invalid_price_rows() -> None:
    yml_payload = b"""<yml_catalog><shop><offers>
      <offer id="bad-1" available="true">
        <url>https://merchant.test/bad</url>
        <name>Broken price</name>
        <price>not-a-price</price>
        <currencyId>RUB</currencyId>
      </offer>
    </offers></shop></yml_catalog>"""

    offers = list(parse_advcake_yml_feed(yml_payload, store_domain="merchant.test"))

    assert offers == []
