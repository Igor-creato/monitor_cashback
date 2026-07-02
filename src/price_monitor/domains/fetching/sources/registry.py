from __future__ import annotations

from price_monitor.domains.fetching.sources.base import SourceAdapter
from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter

_GENERIC = GenericHtmlAdapter()


def get_adapter_for_source(source_domain: str) -> SourceAdapter:
    return _GENERIC
