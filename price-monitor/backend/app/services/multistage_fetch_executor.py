from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.extraction import (
    ExtractedProductData,
    ExtractionError,
    PriceNotFoundError,
    RequiredFieldNotFoundError,
    extract_product_data,
)
from app.fetchers.base import FetchedPage, FetchError, PriceFetchResult
from app.fetchers.browser_fetcher import BrowserFetchResult, BrowserPageFetcher
from app.fetchers.camoufox_fetcher import CamoufoxUnavailableError, fetch_with_camoufox
from app.fetchers.http_fetcher import HTTPPriceFetcher
from app.models.monitoring import TrackedProduct
from app.services.fetch_attempts import record_fetch_attempt
from app.services.fetch_strategy import FetchStrategyDecision, select_fetch_strategy
from app.services.product_feeds import (
    build_price_result_from_feed_item,
    feed_item_is_fresh,
    find_feed_item_for_product,
)
from app.services.proxy_manager import lease_proxy, report_proxy_result
from app.services.source_health import record_source_event
from app.services.source_quarantine import apply_source_quarantine_policy
from app.services.user_limits import UserPriceMonitorLimits
from app.transports.base import (
    TransportNetworkError,
    TransportResponse,
    TransportTimeoutError,
    TransportUnavailableError,
)
from app.transports.curl_cffi_transport import CurlCffiTransport

PROXY_HTTP_STRATEGIES = frozenset(
    {
        "cheap_proxy_http",
        "standard_proxy_http",
        "residential_proxy_http",
        "premium_proxy_http",
    }
)
BROWSER_STRATEGIES = frozenset({"crawl4ai", "playwright"})
FALLBACK_ERROR_TYPES = frozenset({"http_403", "http_429"})
SOURCE_HEALTH_EVENT_TYPES = frozenset(
    {
        "success",
        "timeout",
        "http_403",
        "http_429",
        "parser_error",
        "captcha_detected",
        "price_not_found",
    }
)
SOURCE_QUARANTINE_POLICY_EVENTS = frozenset(
    {"http_403", "http_429", "parser_error", "captcha_detected"}
)
FALLBACK_CHAINS: dict[str, tuple[str, ...]] = {
    "cheap_proxy_http": ("standard_proxy_http", "residential_proxy_http"),
    "standard_proxy_http": ("residential_proxy_http",),
    "residential_proxy_http": ("camoufox",),
}


@dataclass
class ProductFetchExecutionContext:
    session: Session
    user_limits: UserPriceMonitorLimits | None = None
    fetch_job_id: int | None = None
    worker_name: str | None = None
    now: datetime | None = None
    cost_budget_exceeded: bool = False
    strategy_selector: Callable[..., FetchStrategyDecision] = select_fetch_strategy
    find_feed_item: Callable[..., Any] = find_feed_item_for_product
    feed_item_is_fresh: Callable[..., bool] = feed_item_is_fresh
    build_feed_result: Callable[[Any], PriceFetchResult] = (
        build_price_result_from_feed_item
    )
    http_fetcher: Any | None = None
    curl_transport: Any | None = None
    browser_fetcher: Any | None = None
    camoufox_fetcher: Callable[..., BrowserFetchResult] = fetch_with_camoufox
    proxy_leaser: Callable[..., Any] = lease_proxy
    proxy_reporter: Callable[..., Any] = report_proxy_result
    attempt_recorder: Callable[..., Any] = record_fetch_attempt
    health_recorder: Callable[..., Any] = record_source_event
    quarantine_policy: Callable[..., Any] = apply_source_quarantine_policy
    schema_resolver: Callable[[TrackedProduct], Any] | None = None
    wildberries_cards_fetcher: (
        Callable[[str, float | None], TransportResponse] | None
    ) = None


class FetchPipelineFailed(Exception):
    def __init__(
        self,
        *,
        tracked_product_id: int,
        source_code: str,
        attempted_strategies: list[str],
        last_error_type: str,
    ) -> None:
        self.tracked_product_id = tracked_product_id
        self.source_code = source_code
        self.attempted_strategies = attempted_strategies
        self.last_error_type = last_error_type
        super().__init__(
            "fetch pipeline failed for "
            f"{source_code}:{tracked_product_id} after "
            f"{', '.join(attempted_strategies) or 'no attempts'} "
            f"({last_error_type})"
        )


@dataclass(frozen=True)
class _AttemptMetadata:
    http_status: int | None = None
    response_ms: int | None = None
    bytes_downloaded: int | None = None
    proxy_pool_id: int | None = None
    proxy_endpoint_id: int | None = None
    product_data_found: bool = False
    price_found: bool = False
    image_found: bool = False


def execute_product_fetch(
    tracked_product_id: int,
    context: ProductFetchExecutionContext,
) -> PriceFetchResult:
    tracked_product = context.session.get(TrackedProduct, tracked_product_id)
    if tracked_product is None:
        raise FetchPipelineFailed(
            tracked_product_id=tracked_product_id,
            source_code="",
            attempted_strategies=[],
            last_error_type="tracked_product_not_found",
        )

    feed_item = context.find_feed_item(tracked_product, session=context.session)
    has_fresh_feed_data = (
        feed_item is not None
        and context.feed_item_is_fresh(feed_item, now=context.now) is True
    )
    decision = context.strategy_selector(
        tracked_product.source,
        session=context.session,
        user_limits=context.user_limits,
        has_fresh_feed_data=has_fresh_feed_data,
        cost_budget_exceeded=context.cost_budget_exceeded,
        now=context.now,
    )

    if decision.strategy == "quarantine":
        context.attempt_recorder(
            tracked_product_id=tracked_product.id,
            source_code=tracked_product.source,
            strategy="quarantine",
            status="quarantined",
            fetch_job_id=context.fetch_job_id,
            worker_name=context.worker_name,
            error_type=decision.reason,
            session=context.session,
        )
        raise FetchPipelineFailed(
            tracked_product_id=tracked_product.id,
            source_code=tracked_product.source,
            attempted_strategies=[],
            last_error_type=decision.reason,
        )

    attempted: list[str] = []
    last_error_type = "unknown"
    strategies = _strategy_chain(decision)

    for strategy in strategies:
        attempted.append(strategy)
        try:
            result, metadata = _execute_strategy(
                strategy,
                tracked_product,
                context,
                decision,
                feed_item=feed_item,
            )
        except Exception as exc:
            error_type = _error_type(exc)
            last_error_type = error_type
            metadata = _metadata_from_exception(exc)
            _record_attempt(
                context,
                tracked_product,
                strategy=strategy,
                status="failed",
                error_type=error_type,
                metadata=metadata,
            )
            _record_source_health(context, tracked_product.source, error_type, metadata)
            if _should_fallback(error_type, decision, attempted, strategies):
                continue
            raise FetchPipelineFailed(
                tracked_product_id=tracked_product.id,
                source_code=tracked_product.source,
                attempted_strategies=attempted,
                last_error_type=last_error_type,
            ) from exc

        _record_attempt(
            context,
            tracked_product,
            strategy=strategy,
            status="success",
            error_type=None,
            metadata=metadata,
        )
        _record_source_health(context, tracked_product.source, "success", metadata)
        return result

    raise FetchPipelineFailed(
        tracked_product_id=tracked_product.id,
        source_code=tracked_product.source,
        attempted_strategies=attempted,
        last_error_type=last_error_type,
    )


def _execute_strategy(
    strategy: str,
    tracked_product: TrackedProduct,
    context: ProductFetchExecutionContext,
    decision: FetchStrategyDecision,
    *,
    feed_item: Any,
) -> tuple[PriceFetchResult, _AttemptMetadata]:
    if strategy == "feed":
        if feed_item is None:
            raise FetchError("price_not_found", "fresh feed item is missing")
        result = context.build_feed_result(feed_item)
        return result, _metadata_from_result(result)

    if strategy == "direct_http":
        fetcher = context.http_fetcher or HTTPPriceFetcher(
            timeout=decision.timeout_seconds
        )
        result = fetcher.fetch(tracked_product.canonical_url)
        return result, _metadata_from_result(result)

    if strategy == "curl_cffi_http":
        result, response = _execute_curl_cffi_strategy(
            tracked_product,
            context,
            timeout=decision.timeout_seconds,
        )
        return result, _metadata_from_transport(response, result)

    if strategy in PROXY_HTTP_STRATEGIES:
        return _execute_proxy_http_strategy(
            strategy,
            tracked_product,
            context,
            decision,
        )

    if strategy in BROWSER_STRATEGIES:
        fetcher = context.browser_fetcher or BrowserPageFetcher()
        page = fetcher.fetch_rendered_html(
            tracked_product.canonical_url,
            proxy_url=None,
            timeout=decision.timeout_seconds,
        )
        result = _result_from_browser_page(page, tracked_product, context)
        return result, _metadata_from_browser(page, result)

    if strategy == "camoufox":
        page = context.camoufox_fetcher(
            tracked_product.canonical_url,
            proxy_url=None,
            timeout=decision.timeout_seconds,
        )
        result = _result_from_browser_page(page, tracked_product, context)
        return result, _metadata_from_browser(page, result)

    raise FetchError("source_unavailable", f"unsupported strategy: {strategy}")


def _execute_curl_cffi_strategy(
    tracked_product: TrackedProduct,
    context: ProductFetchExecutionContext,
    *,
    timeout: float | None,
) -> tuple[PriceFetchResult, TransportResponse]:
    if tracked_product.source == "wildberries":
        url = _wildberries_cards_api_url(tracked_product.external_product_id)
        fetcher = context.wildberries_cards_fetcher or _fetch_wildberries_cards_response
        response = fetcher(url, timeout)
        result = _wildberries_result_from_cards_response(
            response,
            tracked_product,
            context,
        )
        return result, response

    response = _fetch_with_curl(
        context,
        tracked_product.canonical_url,
        proxy_url=None,
        timeout=timeout,
    )
    result = _result_from_raw_response(response, tracked_product, context)
    return result, response


def _execute_proxy_http_strategy(
    strategy: str,
    tracked_product: TrackedProduct,
    context: ProductFetchExecutionContext,
    decision: FetchStrategyDecision,
) -> tuple[PriceFetchResult, _AttemptMetadata]:
    lease = context.proxy_leaser(
        tracked_product.source,
        "price_fetch",
        _proxy_job_id(context, tracked_product, strategy),
        session=context.session,
        now=context.now,
    )
    if lease is None:
        raise RuntimeError("no_proxy_lease")

    endpoint = lease.endpoint
    proxy_url = endpoint.endpoint_ref
    base_metadata = _AttemptMetadata(
        proxy_pool_id=getattr(endpoint, "pool_id", None),
        proxy_endpoint_id=getattr(endpoint, "id", None),
    )

    try:
        response = _fetch_with_curl(
            context,
            tracked_product.canonical_url,
            proxy_url=proxy_url,
            timeout=decision.timeout_seconds,
        )
        result = _result_from_raw_response(response, tracked_product, context)
    except Exception as exc:
        metadata = _metadata_from_exception(exc, base=base_metadata)
        context.proxy_reporter(
            lease.lease_token,
            "failed",
            _proxy_event_type(_error_type(exc)),
            metadata.response_ms,
            session=context.session,
            now=context.now,
        )
        exc._fetch_metadata = metadata  # type: ignore[attr-defined]
        raise

    metadata = _metadata_from_transport(
        response,
        result,
        proxy_pool_id=base_metadata.proxy_pool_id,
        proxy_endpoint_id=base_metadata.proxy_endpoint_id,
    )
    context.proxy_reporter(
        lease.lease_token,
        "success",
        "success",
        metadata.response_ms,
        session=context.session,
        now=context.now,
    )
    return result, metadata


def _fetch_with_curl(
    context: ProductFetchExecutionContext,
    url: str,
    *,
    proxy_url: str | None,
    timeout: float | None,
) -> TransportResponse:
    transport = context.curl_transport or CurlCffiTransport()
    try:
        response = transport.fetch(url, proxy_url=proxy_url, timeout=timeout)
    except TransportTimeoutError as exc:
        raise FetchError("timeout") from exc
    except (TransportNetworkError, TransportUnavailableError) as exc:
        raise FetchError("source_unavailable") from exc

    if response.status_code == 403:
        error = FetchError("http_403")
        error._fetch_metadata = _metadata_from_transport_response(response)  # type: ignore[attr-defined]
        raise error
    if response.status_code == 429:
        error = FetchError("http_429")
        error._fetch_metadata = _metadata_from_transport_response(response)  # type: ignore[attr-defined]
        raise error
    if response.status_code >= 500:
        error = FetchError("source_unavailable")
        error._fetch_metadata = _metadata_from_transport_response(response)  # type: ignore[attr-defined]
        raise error
    if response.status_code >= 400:
        error = FetchError("bad_content")
        error._fetch_metadata = _metadata_from_transport_response(response)  # type: ignore[attr-defined]
        raise error
    if not response.text:
        error = FetchError("bad_content")
        error._fetch_metadata = _metadata_from_transport_response(response)  # type: ignore[attr-defined]
        raise error
    return response


def _fetch_wildberries_cards_response(
    url: str,
    timeout: float | None,
) -> TransportResponse:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout or 5.0) as response:
            body = response.read()
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return TransportResponse(
                status_code=response.status,
                headers=dict(response.headers.items()),
                text=body.decode(response.headers.get_content_charset() or "utf-8"),
                content_type=response.headers.get("Content-Type", ""),
                elapsed_ms=elapsed_ms,
                final_url=response.url,
            )
    except TimeoutError as exc:
        raise FetchError("timeout") from exc
    except urllib.error.HTTPError as exc:
        body = exc.read()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        error = FetchError(_http_error_type(exc.code))
        error._fetch_metadata = _AttemptMetadata(  # type: ignore[attr-defined]
            http_status=exc.code,
            response_ms=elapsed_ms,
            bytes_downloaded=len(body),
        )
        raise error from exc
    except urllib.error.URLError as exc:
        raise FetchError("source_unavailable") from exc


def _http_error_type(status_code: int) -> str:
    if status_code == 403:
        return "http_403"
    if status_code == 429:
        return "http_429"
    if status_code >= 500:
        return "source_unavailable"
    return "bad_content"


def _result_from_raw_response(
    response: TransportResponse,
    tracked_product: TrackedProduct,
    context: ProductFetchExecutionContext,
) -> PriceFetchResult:
    schema = _resolve_schema(context, tracked_product)
    page = FetchedPage(
        content=response.text,
        content_type=response.content_type,
        fetched_at=context.now or datetime.now(),
        http_status=response.status_code,
        response_ms=response.elapsed_ms,
        bytes_downloaded=len(response.text.encode()),
    )
    extracted = extract_product_data(page.content, schema)
    return _result_from_extracted(
        extracted,
        page.fetched_at,
        default_currency=tracked_product.currency,
    )


def _result_from_browser_page(
    page: BrowserFetchResult,
    tracked_product: TrackedProduct,
    context: ProductFetchExecutionContext,
) -> PriceFetchResult:
    if page.response_status == 403:
        error = FetchError("http_403")
        error._fetch_metadata = _metadata_from_browser_response(page)  # type: ignore[attr-defined]
        raise error
    if page.response_status == 429:
        error = FetchError("http_429")
        error._fetch_metadata = _metadata_from_browser_response(page)  # type: ignore[attr-defined]
        raise error

    schema = _resolve_schema(context, tracked_product)
    extracted = extract_product_data(page.html, schema)
    return _result_from_extracted(
        extracted,
        context.now or datetime.now(),
        default_currency=tracked_product.currency,
    )


def _wildberries_cards_api_url(external_product_id: str) -> str:
    product_id = _wildberries_product_id(external_product_id)
    return (
        "https://card.wb.ru/cards/v4/detail?"
        f"appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
    )


def _wildberries_result_from_cards_response(
    response: TransportResponse,
    tracked_product: TrackedProduct,
    context: ProductFetchExecutionContext,
) -> PriceFetchResult:
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise FetchError("parser_error") from exc

    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list) or not products:
        raise FetchError("price_not_found")

    expected_product_id = _wildberries_product_id(tracked_product.external_product_id)
    product = _wildberries_find_product(products, expected_product_id)
    if product is None:
        raise FetchError("price_not_found")

    current_price = _wildberries_price(product, "product")
    if current_price is None:
        raise FetchError("price_not_found")

    old_price = _wildberries_price(product, "basic")
    if old_price == current_price:
        old_price = None

    return PriceFetchResult(
        product_name=_optional_text(product.get("name")),
        price_current=current_price,
        price_old=old_price,
        currency="RUB",
        availability=_wildberries_available(product),
        seller_name=_optional_text(product.get("supplier")),
        image_url=_wildberries_image_url(expected_product_id),
        fetched_at=context.now or datetime.now(),
    )


def _wildberries_find_product(
    products: list[Any],
    expected_product_id: int,
) -> dict[str, Any] | None:
    first_mapping: dict[str, Any] | None = None
    for product in products:
        if not isinstance(product, dict):
            continue
        if first_mapping is None:
            first_mapping = product
        if product.get("id") == expected_product_id:
            return product
    return first_mapping


def _wildberries_product_id(value: str) -> int:
    try:
        product_id = int(value)
    except (TypeError, ValueError) as exc:
        raise FetchError("parser_error", "invalid wildberries product id") from exc
    if product_id <= 0:
        raise FetchError("parser_error", "invalid wildberries product id")
    return product_id


def _wildberries_price(product: dict[str, Any], key: str) -> Decimal | None:
    for size in product.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        price = size.get("price")
        if not isinstance(price, dict):
            continue
        amount = price.get(key)
        if amount not in {None, ""}:
            return _wildberries_money(amount)

    amount = product.get(key)
    if amount in {None, ""}:
        return None
    return _wildberries_money(amount)


def _wildberries_money(value: Any) -> Decimal:
    try:
        return (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise FetchError("price_not_found") from exc


def _wildberries_available(product: dict[str, Any]) -> bool:
    quantity = product.get("totalQuantity")
    if quantity is not None:
        try:
            return int(quantity) > 0
        except (TypeError, ValueError):
            return True

    for size in product.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        stocks = size.get("stocks")
        if isinstance(stocks, list) and stocks:
            return True
    return True


def _wildberries_image_url(product_id: int) -> str:
    volume = product_id // 100000
    part = product_id // 1000
    basket = _wildberries_basket(volume)
    return (
        f"https://basket-{basket:02d}.wbbasket.ru/"
        f"vol{volume}/part{part}/{product_id}/images/big/1.webp"
    )


def _wildberries_basket(volume: int) -> int:
    ranges = (
        (143, 1),
        (287, 2),
        (431, 3),
        (719, 4),
        (1007, 5),
        (1061, 6),
        (1115, 7),
        (1169, 8),
        (1313, 9),
        (1601, 10),
        (1655, 11),
        (1919, 12),
        (2045, 13),
        (2189, 14),
        (2405, 15),
        (2621, 16),
        (2837, 17),
        (3053, 18),
        (3269, 19),
        (3485, 20),
        (3701, 21),
        (3917, 22),
        (4133, 23),
        (4349, 24),
        (4565, 25),
        (4877, 26),
        (5189, 27),
        (5501, 28),
        (5813, 29),
        (6125, 30),
        (6437, 31),
        (6749, 32),
        (7061, 33),
        (7373, 34),
        (7685, 35),
        (7997, 36),
    )
    for upper_bound, basket in ranges:
        if volume <= upper_bound:
            return basket
    return 37


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_schema(
    context: ProductFetchExecutionContext,
    tracked_product: TrackedProduct,
) -> Any:
    if context.schema_resolver is None:
        raise FetchError("parser_error", "extraction schema is required")
    schema = context.schema_resolver(tracked_product)
    if schema is None:
        raise FetchError("parser_error", "extraction schema is required")
    return schema


def _result_from_extracted(
    extracted: ExtractedProductData,
    fetched_at: datetime,
    *,
    default_currency: str | None,
) -> PriceFetchResult:
    if extracted.price_current is None:
        raise PriceNotFoundError()

    return PriceFetchResult(
        product_name=extracted.title,
        price_current=extracted.price_current,
        price_old=extracted.price_old,
        currency=extracted.currency or default_currency or "RUB",
        availability=extracted.availability
        if extracted.availability is not None
        else True,
        seller_name=extracted.seller_name,
        image_url=extracted.image_url,
        fetched_at=fetched_at,
    )


def _strategy_chain(decision: FetchStrategyDecision) -> list[str]:
    chain = [decision.strategy]
    if not decision.allow_fallback:
        return chain

    for fallback in FALLBACK_CHAINS.get(decision.strategy, ()):
        if fallback not in chain:
            chain.append(fallback)
    return chain


def _should_fallback(
    error_type: str,
    decision: FetchStrategyDecision,
    attempted: list[str],
    strategies: list[str],
) -> bool:
    return (
        decision.allow_fallback
        and error_type in FALLBACK_ERROR_TYPES
        and len(attempted) < len(strategies)
    )


def _record_attempt(
    context: ProductFetchExecutionContext,
    tracked_product: TrackedProduct,
    *,
    strategy: str,
    status: str,
    error_type: str | None,
    metadata: _AttemptMetadata,
) -> None:
    context.attempt_recorder(
        tracked_product_id=tracked_product.id,
        source_code=tracked_product.source,
        strategy=strategy,
        status=status,
        fetch_job_id=context.fetch_job_id,
        proxy_pool_id=metadata.proxy_pool_id,
        proxy_endpoint_id=metadata.proxy_endpoint_id,
        worker_name=context.worker_name,
        error_type=error_type,
        http_status=metadata.http_status,
        response_ms=metadata.response_ms,
        bytes_downloaded=metadata.bytes_downloaded,
        product_data_found=metadata.product_data_found,
        price_found=metadata.price_found,
        image_found=metadata.image_found,
        session=context.session,
    )


def _record_source_health(
    context: ProductFetchExecutionContext,
    source_code: str,
    event_type: str,
    metadata: _AttemptMetadata,
) -> None:
    if event_type not in SOURCE_HEALTH_EVENT_TYPES:
        return
    context.health_recorder(
        source_code,
        event_type,
        status_code=metadata.http_status,
        response_ms=metadata.response_ms,
        session=context.session,
    )
    if event_type not in SOURCE_QUARANTINE_POLICY_EVENTS:
        return
    context.quarantine_policy(
        source_code,
        event_type,
        session=context.session,
        now=context.now,
    )


def _metadata_from_result(result: PriceFetchResult) -> _AttemptMetadata:
    return _AttemptMetadata(
        product_data_found=True,
        price_found=result.price_current is not None,
        image_found=bool(result.image_url),
    )


def _metadata_from_transport(
    response: TransportResponse,
    result: PriceFetchResult,
    *,
    proxy_pool_id: int | None = None,
    proxy_endpoint_id: int | None = None,
) -> _AttemptMetadata:
    return _AttemptMetadata(
        http_status=response.status_code,
        response_ms=response.elapsed_ms,
        bytes_downloaded=len(response.text.encode()),
        proxy_pool_id=proxy_pool_id,
        proxy_endpoint_id=proxy_endpoint_id,
        product_data_found=True,
        price_found=result.price_current is not None,
        image_found=bool(result.image_url),
    )


def _metadata_from_browser(
    page: BrowserFetchResult,
    result: PriceFetchResult,
) -> _AttemptMetadata:
    return _AttemptMetadata(
        http_status=page.response_status,
        response_ms=page.elapsed_ms,
        bytes_downloaded=len(page.html.encode()),
        product_data_found=True,
        price_found=result.price_current is not None,
        image_found=bool(result.image_url),
    )


def _metadata_from_exception(
    exc: Exception,
    *,
    base: _AttemptMetadata | None = None,
) -> _AttemptMetadata:
    metadata = getattr(exc, "_fetch_metadata", None)
    if isinstance(metadata, _AttemptMetadata):
        if base is None:
            return metadata
        return _merge_metadata(base, metadata)
    return base or _AttemptMetadata()


def _metadata_from_transport_response(response: TransportResponse) -> _AttemptMetadata:
    return _AttemptMetadata(
        http_status=response.status_code,
        response_ms=response.elapsed_ms,
        bytes_downloaded=len(response.text.encode()),
    )


def _metadata_from_browser_response(page: BrowserFetchResult) -> _AttemptMetadata:
    return _AttemptMetadata(
        http_status=page.response_status,
        response_ms=page.elapsed_ms,
        bytes_downloaded=len(page.html.encode()),
    )


def _merge_metadata(
    base: _AttemptMetadata,
    overlay: _AttemptMetadata,
) -> _AttemptMetadata:
    return _AttemptMetadata(
        http_status=overlay.http_status,
        response_ms=overlay.response_ms,
        bytes_downloaded=overlay.bytes_downloaded,
        proxy_pool_id=base.proxy_pool_id,
        proxy_endpoint_id=base.proxy_endpoint_id,
        product_data_found=overlay.product_data_found,
        price_found=overlay.price_found,
        image_found=overlay.image_found,
    )


def _error_type(exc: Exception) -> str:
    if isinstance(exc, FetchError):
        return exc.error_type
    if isinstance(exc, PriceNotFoundError):
        return "price_not_found"
    if isinstance(exc, RequiredFieldNotFoundError | ExtractionError):
        return "parser_error"
    if isinstance(exc, CamoufoxUnavailableError):
        return "browser_unavailable"
    return type(exc).__name__


def _proxy_event_type(error_type: str) -> str:
    if error_type in {"http_403", "http_429", "timeout"}:
        return error_type
    return "error"


def _proxy_job_id(
    context: ProductFetchExecutionContext,
    tracked_product: TrackedProduct,
    strategy: str,
) -> str:
    if context.fetch_job_id is not None:
        return str(context.fetch_job_id)
    return f"product-{tracked_product.id}-{strategy}"
