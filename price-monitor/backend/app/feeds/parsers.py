"""Parsers for product feed fixtures (CSV/JSON/YAML/XML).

These functions take raw feed content and return a list of plain ``dict``
records keyed by *logical* feed field names (``product_id``, ``title``,
``url``, ``price``, ``old_price``, ``currency``, ``category_id``,
``image_url``, ``availability``).

Parsers are pure: no database access, no HTTP. Type coercion (e.g. price to
``Decimal``) is intentionally left to the importer so that item-level
validation lives in a single place.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping
from typing import Any
from xml.etree import ElementTree as ET

import yaml

__all__ = [
    "UnsupportedFeedFormatError",
    "parse_csv",
    "parse_json",
    "parse_yaml",
    "parse_xml",
    "parse_feed",
    "FORMAT_PARSERS",
]


class UnsupportedFeedFormatError(ValueError):
    """Raised when a feed format has no registered parser."""


# Collection keys we accept when the top-level JSON/YAML payload is a mapping
# wrapping the records instead of being a bare list.
_COLLECTION_KEYS = ("items", "offers", "products", "data")

# Child tags / attributes recognised inside an XML ``<offer>``/``<item>`` node,
# mapped to logical feed field names. Kept minimal for test fixtures.
_XML_FIELD_TAGS = {
    "url": "url",
    "price": "price",
    "oldprice": "old_price",
    "old_price": "old_price",
    "name": "title",
    "title": "title",
    "picture": "image_url",
    "image_url": "image_url",
    "categoryid": "category_id",
    "category_id": "category_id",
    "currencyid": "currency",
    "currency": "currency",
    "available": "availability",
    "availability": "availability",
}


def _decode(content: str | bytes) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8")
    return content


def _apply_mapping(
    record: Mapping[str, Any],
    fields_mapping: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Rename raw record keys to logical feed field names.

    ``fields_mapping`` maps *source* keys to *logical* keys. Keys not present
    in the mapping are passed through unchanged. When the mapping is empty or
    ``None`` the record is returned as-is (raw keys are already logical).
    """

    if not fields_mapping:
        return dict(record)

    mapped: dict[str, Any] = {}
    for key, value in record.items():
        mapped[fields_mapping.get(key, key)] = value
    return mapped


def parse_csv(
    content: str | bytes,
    *,
    fields_mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(_decode(content)))
    return [_apply_mapping(row, fields_mapping) for row in reader]


def _records_from_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in _COLLECTION_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def parse_json(
    content: str | bytes,
    *,
    fields_mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(_decode(content))
    records = _records_from_payload(payload)
    return [_apply_mapping(row, fields_mapping) for row in records]


def parse_yaml(
    content: str | bytes,
    *,
    fields_mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    payload = yaml.safe_load(_decode(content))
    records = _records_from_payload(payload)
    return [_apply_mapping(row, fields_mapping) for row in records]


def _offer_to_record(offer: ET.Element) -> dict[str, Any]:
    record: dict[str, Any] = {}

    offer_id = offer.get("id")
    if offer_id is not None:
        record["product_id"] = offer_id

    for child in offer:
        logical = _XML_FIELD_TAGS.get(child.tag.lower())
        if logical is None:
            continue
        text = child.text
        record[logical] = text.strip() if isinstance(text, str) else text

    return record


def parse_xml(
    content: str | bytes,
    *,
    fields_mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(_decode(content))
    offers = [
        element
        for element in root.iter()
        if element.tag.lower() in {"offer", "item"}
    ]
    return [_apply_mapping(_offer_to_record(offer), fields_mapping) for offer in offers]


FORMAT_PARSERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "csv": parse_csv,
    "json": parse_json,
    "yaml": parse_yaml,
    "yml": parse_yaml,
    "xml": parse_xml,
}


def parse_feed(
    content: str | bytes,
    fmt: str,
    *,
    fields_mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    parser = FORMAT_PARSERS.get(fmt.strip().lower())
    if parser is None:
        raise UnsupportedFeedFormatError(f"Unsupported feed format: {fmt!r}")
    return parser(content, fields_mapping=fields_mapping)
