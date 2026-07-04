from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from io import StringIO
from typing import Any, cast

from defusedxml import ElementTree

from price_monitor.price_compare.feed import NormalizedOffer, normalize_feed_item


def parse_admitad_csv_feed(
    content: bytes, *, store_domain: str, source: str = "admitad_product_feed"
) -> Iterable[NormalizedOffer]:
    text = content.decode("utf-8-sig")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(StringIO(text), delimiter=delimiter)
    for row in reader:
        offer = _normalize_or_none(_admitad_row(row), source=source, store_domain=store_domain)
        if offer is not None:
            yield offer


def parse_admitad_xml_feed(
    content: bytes, *, store_domain: str, source: str = "admitad_product_feed"
) -> Iterable[NormalizedOffer]:
    root = ElementTree.fromstring(content)
    for element in _iter_product_elements(root):
        raw = {
            "external_id": _text(element, "id", "external_id", "product_id"),
            "title": _text(element, "title", "name"),
            "url": _text(element, "url", "product_url", "link"),
            "price": _text(element, "price"),
            "currency": _text(element, "currency", "currencyId"),
            "availability": _text(element, "availability", "available"),
            "image_url": _text(element, "image", "picture", "image_url"),
            "category": _text(element, "category", "category_name"),
            "brand": _text(element, "brand", "vendor"),
        }
        offer = _normalize_or_none(raw, source=source, store_domain=store_domain)
        if offer is not None:
            yield offer


def parse_advcake_yml_feed(
    content: bytes, *, store_domain: str, source: str = "advcake_product_feed"
) -> Iterable[NormalizedOffer]:
    root = ElementTree.fromstring(content)
    for element in root.findall(".//offer"):
        raw = {
            "external_id": _attribute(element, "id"),
            "title": _text(element, "name")
            or _join_non_empty(_text(element, "vendor"), _text(element, "model")),
            "url": _text(element, "url"),
            "price": _text(element, "price"),
            "currency": _text(element, "currencyId", "currency"),
            "availability": "unknown",
            "image_url": _text(element, "picture"),
            "category": _text(element, "categoryId", "category"),
            "brand": _text(element, "vendor"),
        }
        offer = _normalize_or_none(raw, source=source, store_domain=store_domain)
        if offer is not None:
            yield offer


def _admitad_row(row: Mapping[str, str | None]) -> dict[str, object]:
    return {
        "external_id": _first_mapping_value(row, "external_id", "id", "product_id"),
        "title": _first_mapping_value(row, "title", "name"),
        "url": _first_mapping_value(row, "url", "product_url", "link"),
        "price": _first_mapping_value(row, "price"),
        "currency": _first_mapping_value(row, "currency", "currencyId"),
        "availability": _first_mapping_value(row, "availability", "available"),
        "image_url": _first_mapping_value(row, "image_url", "image", "picture"),
        "category": _first_mapping_value(row, "category", "category_name"),
        "brand": _first_mapping_value(row, "brand", "vendor"),
    }


def _normalize_or_none(
    raw: Mapping[str, object], *, source: str, store_domain: str
) -> NormalizedOffer | None:
    offer = normalize_feed_item(raw, source=source, store_domain=store_domain)
    if not offer.title or not offer.url or offer.price is None:
        return None
    return offer


def _iter_product_elements(root: Any) -> Iterable[Any]:
    products = list(cast(Iterable[Any], root.findall(".//product")))
    if products:
        return products
    return list(cast(Iterable[Any], root.findall(".//offer")))


def _text(element: Any, *names: str) -> str:
    for name in names:
        child = element.find(name)
        text_value = getattr(child, "text", None)
        if isinstance(text_value, str) and text_value.strip():
            return text_value.strip()
    return ""


def _attribute(element: Any, name: str) -> str:
    attributes = getattr(element, "attrib", {})
    if not isinstance(attributes, Mapping):
        return ""
    value = attributes.get(name)
    return value.strip() if isinstance(value, str) else ""


def _first_mapping_value(row: Mapping[str, str | None], *names: str) -> str:
    normalized = {key.strip().lower(): value for key, value in row.items() if key is not None}
    for name in names:
        value = normalized.get(name.lower())
        if value:
            return value.strip()
    return ""


def _join_non_empty(*values: str) -> str:
    return " ".join(value for value in values if value)
