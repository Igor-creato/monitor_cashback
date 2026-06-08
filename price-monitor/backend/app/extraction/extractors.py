from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.extraction.errors import (
    ExtractionSchemaError,
    PriceNotFoundError,
    RequiredFieldNotFoundError,
    TitleNotFoundError,
)
from app.extraction.schemas import ExtractedProductData, ExtractionSchema

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "₽": "RUB",
    "руб": "RUB",
    "р": "RUB",
    "€": "EUR",
    "£": "GBP",
}


def extract_product_data(
    content: dict[str, Any] | str | bytes,
    schema: ExtractionSchema,
) -> ExtractedProductData:
    values = (
        _extract_json_values(content, schema)
        if schema.content_type == "json"
        else _extract_html_values(content, schema)
    )

    currency = _normalize_currency(values.get("currency"))
    price_current, inferred_currency = _normalize_price(values.get("price_current"))
    price_old, old_price_currency = _normalize_price(values.get("price_old"))
    if currency is None:
        currency = inferred_currency or old_price_currency

    result = ExtractedProductData(
        title=_normalize_text(values.get("title")),
        price_current=price_current,
        price_old=price_old,
        currency=currency,
        image_url=_normalize_text(values.get("image_url")),
        availability=_normalize_availability(values.get("availability")),
        seller_name=_normalize_text(values.get("seller_name")),
        source_status="ok",
        extraction_schema_version=schema.version,
    )
    _validate_required_fields(result, schema.required_fields)
    return result


def _extract_json_values(
    content: dict[str, Any] | str | bytes,
    schema: ExtractionSchema,
) -> dict[str, Any]:
    payload = _json_payload(content)
    return {
        "title": _resolve_dotted_path(payload, schema.title_path),
        "price_current": _resolve_dotted_path(payload, schema.price_path),
        "price_old": _resolve_dotted_path(payload, schema.old_price_path),
        "currency": _resolve_dotted_path(payload, schema.currency_path),
        "image_url": _resolve_dotted_path(payload, schema.image_path),
        "availability": _resolve_dotted_path(payload, schema.availability_path),
        "seller_name": _resolve_dotted_path(payload, schema.seller_path),
    }


def _extract_html_values(
    content: str | bytes | dict[str, Any],
    schema: ExtractionSchema,
) -> dict[str, Any]:
    if isinstance(content, dict):
        raise ExtractionSchemaError("HTML extraction requires string or bytes content")
    html = content.decode("utf-8") if isinstance(content, bytes) else content
    soup = BeautifulSoup(html, "html.parser")
    return {
        "title": _select_text(soup, schema.css_title),
        "price_current": _select_text(soup, schema.css_price),
        "price_old": _select_text(soup, schema.css_old_price),
        "currency": None,
        "image_url": _select_image(soup, schema.css_image),
        "availability": _select_text(soup, schema.css_availability),
        "seller_name": None,
    }


def _json_payload(content: dict[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ExtractionSchemaError(
            "JSON extraction requires object-like content"
        ) from exc
    if not isinstance(payload, dict):
        raise ExtractionSchemaError("JSON extraction requires top-level object")
    return payload


def _resolve_dotted_path(payload: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _select_text(soup: BeautifulSoup, selector: str | None) -> str | None:
    if not selector:
        return None
    element = soup.select_one(selector)
    if element is None:
        return None
    return element.get_text(" ", strip=True)


def _select_image(soup: BeautifulSoup, selector: str | None) -> str | None:
    if not selector:
        return None
    element = soup.select_one(selector)
    if element is None:
        return None
    if isinstance(element, Tag):
        for attr in ("src", "content"):
            value = element.get(attr)
            if value:
                return str(value).strip()
    return element.get_text(" ", strip=True)


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_currency(value: Any) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    normalized = text.upper()
    if normalized in {"RUB", "USD", "EUR", "GBP"}:
        return normalized
    return _CURRENCY_SYMBOLS.get(text.strip().lower())


def _normalize_price(value: Any) -> tuple[Decimal | None, str | None]:
    text = _normalize_text(value)
    if text is None:
        return None, None
    currency = _infer_currency(text)
    compact = text.replace("\xa0", " ").replace(" ", "")
    compact = re.sub(r"[^\d,.\-]", "", compact)
    if not compact:
        return None, currency
    normalized = _normalize_decimal_separator(compact)
    try:
        return Decimal(normalized), currency
    except (InvalidOperation, ValueError):
        return None, currency


def _infer_currency(text: str) -> str | None:
    lower_text = text.lower()
    for marker, currency in _CURRENCY_SYMBOLS.items():
        if marker in lower_text:
            return currency
    return None


def _normalize_decimal_separator(value: str) -> str:
    if "," not in value:
        return value
    if "." not in value:
        return value.replace(",", ".")
    if value.rfind(",") > value.rfind("."):
        return value.replace(".", "").replace(",", ".")
    return value.replace(",", "")


def _normalize_availability(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "available", "in_stock"}:
        return True
    if normalized in {"0", "false", "no", "unavailable", "out_of_stock"}:
        return False
    return None


def _validate_required_fields(
    result: ExtractedProductData,
    required_fields: list[str],
) -> None:
    for field_name in required_fields:
        if getattr(result, field_name, None) is not None:
            continue
        if field_name == "price_current":
            raise PriceNotFoundError()
        if field_name == "title":
            raise TitleNotFoundError()
        raise RequiredFieldNotFoundError(field_name)
