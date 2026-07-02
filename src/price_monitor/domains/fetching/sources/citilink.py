from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class CitilinkAdapter(GenericHtmlAdapter):
    source_domain = "citilink.ru"
    parser_version = "citilink-v1"
