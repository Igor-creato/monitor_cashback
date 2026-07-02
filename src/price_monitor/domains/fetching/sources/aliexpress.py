from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class AliExpressAdapter(GenericHtmlAdapter):
    source_domain = "aliexpress.com"
    parser_version = "aliexpress-v1"
