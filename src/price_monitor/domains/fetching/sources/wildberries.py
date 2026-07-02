from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class WildberriesAdapter(GenericHtmlAdapter):
    source_domain = "wildberries.ru"
    parser_version = "wildberries-v1"
