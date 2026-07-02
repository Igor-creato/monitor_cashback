from __future__ import annotations

from price_monitor.domains.fetching.sources.aliexpress import AliExpressAdapter
from price_monitor.domains.fetching.sources.citilink import CitilinkAdapter
from price_monitor.domains.fetching.sources.joom import JoomAdapter
from price_monitor.domains.fetching.sources.ozon import OzonAdapter
from price_monitor.domains.fetching.sources.base import SourceAdapter
from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter
from price_monitor.domains.fetching.sources.wildberries import WildberriesAdapter
from price_monitor.domains.fetching.sources.yandex_market import YandexMarketAdapter

_GENERIC = GenericHtmlAdapter()
_ADAPTERS = {
    "aliexpress.com": AliExpressAdapter(),
    "citilink.ru": CitilinkAdapter(),
    "joom.com": JoomAdapter(),
    "wildberries.ru": WildberriesAdapter(),
    "ozon.ru": OzonAdapter(),
    "market.yandex.ru": YandexMarketAdapter(),
}


def get_adapter_for_source(source_domain: str) -> SourceAdapter:
    return _ADAPTERS.get(source_domain, _GENERIC)
