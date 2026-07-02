from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class JoomAdapter(GenericHtmlAdapter):
    source_domain = "joom.com"
    parser_version = "joom-v1"
