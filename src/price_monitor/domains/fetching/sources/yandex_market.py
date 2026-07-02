from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class YandexMarketAdapter(GenericHtmlAdapter):
    source_domain = "market.yandex.ru"
    parser_version = "yandex-market-v1"
