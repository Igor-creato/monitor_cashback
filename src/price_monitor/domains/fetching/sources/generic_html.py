from __future__ import annotations

from decimal import Decimal

from price_monitor.domains.fetching.extraction import (
    detect_fetch_block_reason,
    extract_product_data_with_metadata,
)
from price_monitor.domains.fetching.ports import ProductExtraction
from price_monitor.domains.fetching.sources.base import FetchContext, SourceFetchResult


class GenericHtmlAdapter:
    source_domain = "*"
    parser_version = "generic-html-v1"

    def fetch_product(self, context: FetchContext) -> SourceFetchResult:
        page = context.fetcher.fetch(url=context.canonical_url, proxy_url=context.proxy_url)
        block_reason = detect_fetch_block_reason(page.content)
        if block_reason is not None:
            return SourceFetchResult(
                status=block_reason,
                extraction=None,
                http_status=page.http_status,
                response_ms=page.response_ms,
                reason=block_reason,
                block_reason=block_reason,
                challenge_detected=True,
                parser_version=self.parser_version,
                parser_confidence=None,
                provider_name=None,
                provider_request_id=None,
                provider_cost_minor=None,
                rendered=False,
            )

        extracted = extract_product_data_with_metadata(
            page.content,
            fallback_currency=context.fallback_currency,
        )
        if extracted is None:
            return SourceFetchResult(
                status="product_data_not_found",
                extraction=None,
                http_status=page.http_status,
                response_ms=page.response_ms,
                reason="product_data_not_found",
                block_reason=None,
                challenge_detected=False,
                parser_version=self.parser_version,
                parser_confidence=None,
                provider_name=None,
                provider_request_id=None,
                provider_cost_minor=None,
                rendered=False,
            )

        confidence = Decimal("0.90") if extracted.source == "json-ld" else Decimal("0.40")
        parser_confidence = str(confidence)
        product_extraction = ProductExtraction(
            title=extracted.data.title,
            price_minor=extracted.data.price_minor,
            currency=extracted.data.currency,
            image_url=extracted.data.image_url,
            rating_value=extracted.data.rating_value,
            availability=None,
            canonical_url=context.canonical_url,
            source_product_id=context.source_product_id,
            parser_version=self.parser_version,
            confidence=confidence,
        )
        return SourceFetchResult(
            status="ok",
            extraction=product_extraction,
            http_status=page.http_status,
            response_ms=page.response_ms,
            reason=None,
            block_reason=None,
            challenge_detected=False,
            parser_version=self.parser_version,
            parser_confidence=parser_confidence,
            provider_name=None,
            provider_request_id=None,
            provider_cost_minor=None,
            rendered=False,
        )
