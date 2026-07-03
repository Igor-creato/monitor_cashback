from __future__ import annotations

from typing import Any

from price_monitor.price_compare.live.adapters.base import SearchAdapter
from price_monitor.price_compare.live.adapters.direct_http import DirectHttpSearchAdapter
from price_monitor.price_compare.live.adapters.fixture import FixtureSearchAdapter
from price_monitor.price_compare.schemas import normalize_domain


def get_adapter_for_store(domain: str, config: dict[str, Any]) -> SearchAdapter | None:
    normalized_domain = normalize_domain(domain)
    source_type = str(config.get("source_type", "custom"))
    source_config = _source_config(config)
    fixture_items = source_config.get("live_fixture_items")
    if source_type in {"custom", "live_fixture"} and isinstance(fixture_items, list):
        return FixtureSearchAdapter(domain=normalized_domain, items=_dict_items(fixture_items))
    search_url_template = source_config.get("live_search_url_template")
    if source_type in {"custom", "direct_http"} and isinstance(search_url_template, str):
        return DirectHttpSearchAdapter(
            domain=normalized_domain,
            search_url_template=search_url_template,
        )
    return None


def _source_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("source_config", config)
    return value if isinstance(value, dict) else {}


def _dict_items(items: list[object]) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)]
