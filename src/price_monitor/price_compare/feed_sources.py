from __future__ import annotations

from typing import Any

from price_monitor.price_compare.models import AffiliateFeedSource

_SECRET_DESCRIPTOR_KEYS = {
    "access_token",
    "api_key",
    "client_id",
    "client_secret",
    "feed_url",
    "password",
    "products_csv_link",
    "products_xml_link",
    "secret",
    "token",
    "url",
}


def public_feed_source_payload(feed_source: AffiliateFeedSource) -> dict[str, Any]:
    return {
        "id": feed_source.id,
        "network": feed_source.network,
        "store_domain": feed_source.store_domain,
        "offer_id": feed_source.offer_id,
        "feed_id": feed_source.feed_id,
        "display_name": feed_source.display_name,
        "format": feed_source.format,
        "feed_url_secret": feed_source.feed_url_secret,
        "active": feed_source.active,
        "last_feed_updated_at": (
            feed_source.last_feed_updated_at.isoformat()
            if feed_source.last_feed_updated_at
            else None
        ),
        "descriptor": _redact_descriptor(feed_source.descriptor_payload),
    }


def _redact_descriptor(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_string = str(key)
            if key_string.lower() in _SECRET_DESCRIPTOR_KEYS:
                redacted[key_string] = "[redacted]"
            else:
                redacted[key_string] = _redact_descriptor(item)
        return redacted
    if isinstance(value, list):
        return [_redact_descriptor(item) for item in value]
    return value
