from __future__ import annotations

from typing import Any

from price_monitor.core.config import get_settings
from price_monitor.price_compare.live.adapters.base import SearchAdapter
from price_monitor.price_compare.live.adapters.decodo import DecodoWebSearchAdapter
from price_monitor.price_compare.live.adapters.direct_http import DirectHttpSearchAdapter
from price_monitor.price_compare.live.adapters.fixture import FixtureSearchAdapter
from price_monitor.price_compare.live.adapters.nodemaven import (
    NodeMavenProxySearchAdapter,
    build_proxy_url,
)
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
    if source_type == "managed_provider" and isinstance(search_url_template, str):
        provider = str(source_config.get("provider", "")).strip().lower()
        parser = str(source_config.get("parser", "")).strip()
        if provider == "decodo" and parser:
            settings = get_settings()
            return DecodoWebSearchAdapter(
                domain=normalized_domain,
                search_url_template=search_url_template,
                api_url=settings.decodo_scraper_api_url,
                auth_token=settings.decodo_basic_auth_token,
                parser=parser,
                headless=str(source_config.get("headless", settings.decodo_default_headless)),
                proxy_pool=str(source_config.get("proxy_pool", settings.decodo_default_proxy_pool)),
                device_type=str(
                    source_config.get("device_type", settings.decodo_default_device_type)
                ),
                geo=str(source_config.get("geo", "")),
                locale=str(source_config.get("locale", "")),
                timeout_seconds=settings.decodo_request_timeout_seconds,
            )
        if provider == "nodemaven" and parser:
            settings = get_settings()
            return NodeMavenProxySearchAdapter(
                domain=normalized_domain,
                search_url_template=search_url_template,
                proxy_url=build_proxy_url(
                    proxy_url=settings.nodemaven_proxy_url,
                    host=settings.nodemaven_proxy_host,
                    port=settings.nodemaven_proxy_port,
                    username=settings.nodemaven_proxy_username,
                    password=settings.nodemaven_proxy_password,
                ),
                parser=parser,
                timeout_seconds=settings.nodemaven_request_timeout_seconds,
                verify_ssl=settings.nodemaven_verify_ssl,
            )
    return None


def _source_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("source_config", config)
    return value if isinstance(value, dict) else {}


def _dict_items(items: list[object]) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)]
