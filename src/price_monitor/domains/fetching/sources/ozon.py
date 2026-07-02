from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class OzonAdapter(GenericHtmlAdapter):
    source_domain = "ozon.ru"
    parser_version = "ozon-v1"
