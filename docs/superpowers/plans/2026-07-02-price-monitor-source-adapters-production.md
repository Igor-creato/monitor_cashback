# Price Monitor Source Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the test-stage price monitor work through backend and WordPress UI for individual AliExpress, Citilink, Joom, Wildberries, Ozon, and Yandex Market product URLs, with clear unsupported/non-product errors and safe diagnostics.

**Architecture:** Keep WordPress as the account UI/admin/proxy surface and keep FastAPI as the source policy, URL classification, fetch, extraction, history, and diagnostics service. Add source-aware product URL classification, source adapters behind a registry, fetch attempt metadata, job lifecycle fields, and one global admin refresh cadence setting with default `8` hours.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Celery, pytest, ruff, mypy, WordPress PHP, PHPUnit, Node `node --test`, HMAC-signed WordPress-to-backend requests.

## Global Constraints

- Use RED -> GREEN TDD for every behavior change.
- Prefix all shell commands with `rtk`.
- Keep `F:\cash-back\monitor_cashback` and `F:\wamp64\www\kash-back\wp-content\plugins\cash-back` commits separate.
- Do not store marketplace passwords, unapproved raw cookies, raw browser sessions, provider secrets, proxy credentials, or challenge tokens in database rows, logs, docs, screenshots, fixtures, or git.
- If a source needs Decodo or another managed unblocker account, API key, trial, or paid plan to continue, stop and report exactly: `"Нужно подключение Decodo"`.
- Preserve existing HMAC, idempotency, activation redirect, and WordPress proxy contracts.
- All fetcher, provider, and adapter tests use fake providers or sanitized fixtures. No test performs live marketplace traffic.
- Add one global admin setting `price_refresh_interval_hours`, integer hours, minimum `1`, default `8`.
- Existing per-source `fetch_interval_hours` values remain valid overrides. New sources default to `price_refresh_interval_hours`.
- Do not revert existing uncommitted plugin changes in `admin/class-cashback-price-monitor-admin.php` or `development/test/tests/PriceMonitorAdminTest.php`.

---

## File Structure

Backend files:

- Modify `src/price_monitor/domains/sources/service.py`: settings defaults, effective interval helper, source default cadence.
- Modify `src/price_monitor/domains/sources/schemas.py`: admin settings request schema.
- Modify `src/price_monitor/api/v1/admin.py`: typed settings response.
- Create `src/price_monitor/domains/sources/classification.py`: store-specific product URL classification.
- Modify `src/price_monitor/api/v1/sources.py`: supported-store responses use classifier errors.
- Modify `src/price_monitor/domains/watchlist/service.py`: reject non-product supported-store URLs before creating products.
- Modify `src/price_monitor/domains/products/models.py`: persist `source_product_id`.
- Modify `src/price_monitor/domains/reliability/models.py`: job lifecycle and attempt metadata fields.
- Modify `src/price_monitor/domains/fetching/ports.py`: extraction and provider result dataclasses.
- Create `src/price_monitor/domains/fetching/sources/base.py`: adapter protocol and shared result types.
- Create `src/price_monitor/domains/fetching/sources/registry.py`: source-domain adapter lookup.
- Create `src/price_monitor/domains/fetching/sources/{aliexpress,citilink,joom,wildberries,ozon,yandex_market,generic_html}.py`: source adapters.
- Modify `src/price_monitor/domains/fetching/extraction.py`: extraction confidence, parser version, availability.
- Modify `src/price_monitor/domains/fetching/service.py`: ladder, confidence gating, safe attempt metadata, price writes.
- Create `src/price_monitor/workers/scheduler.py`: due-item fetch job scheduling from effective interval.
- Modify `src/price_monitor/workers/tasks/fetch_product.py`: terminal job statuses and safe exception classification.
- Modify `src/price_monitor/api/v1/products.py`: latest job/attempt summary.
- Modify `src/price_monitor/api/v1/price_history.py`: keep one empty chart state.

Backend tests:

- Modify `tests/unit/test_source_service.py`.
- Create `tests/unit/test_product_url_classifier.py`.
- Modify `tests/integration/test_watchlist_service.py`.
- Modify `tests/contract/test_api_contract.py`.
- Modify `tests/contract/test_admin_api_contract.py`.
- Modify `tests/unit/test_fetch_pipeline.py`.
- Create `tests/unit/test_fetch_scheduler.py`.
- Create `tests/unit/test_source_adapters.py`.
- Modify `tests/contract/test_product_card_contract.py`.

WordPress files:

- Modify `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\admin\class-cashback-price-monitor-admin.php`: admin cadence field and backend payload.
- Modify `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\includes\price-monitor\class-cashback-price-monitor-rest-controller.php`: preserve backend error codes for frontend.
- Modify `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\assets\js\price-monitor-account.js`: new invalid URL copy.
- Modify `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\development\test\tests\PriceMonitorAdminTest.php`.
- Modify `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\development\test\tests\PriceMonitorRestControllerTest.php`.
- Modify `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\tests\price-monitor-account.test.mjs`.

---

### Task 1: Backend Admin Refresh Cadence Setting

**Files:**
- Modify: `src/price_monitor/domains/sources/service.py`
- Modify: `src/price_monitor/domains/sources/schemas.py`
- Modify: `src/price_monitor/api/v1/admin.py`
- Test: `tests/unit/test_source_service.py`
- Test: `tests/contract/test_admin_api_contract.py`

**Interfaces:**
- Consumes: existing `SourceService.get_settings()` and `SourceService.update_settings(values: dict[str, str])`.
- Produces: `DEFAULT_PRICE_REFRESH_INTERVAL_HOURS = 8` and `SourceService.effective_fetch_interval_hours(source: MonitoredSource) -> int`.

- [ ] **Step 1: Write the failing unit test**

Add to `tests/unit/test_source_service.py`:

```python
def test_monitor_settings_include_price_refresh_interval_default_and_updates(
    session: Session,
) -> None:
    service = SourceService(session)

    defaults = service.get_settings()

    assert defaults["price_refresh_interval_hours"] == "8"

    updated = service.update_settings({"price_refresh_interval_hours": "12"})

    assert updated["price_refresh_interval_hours"] == "12"
```

- [ ] **Step 2: Write the failing admin contract assertions**

In `tests/contract/test_admin_api_contract.py::test_admin_source_and_settings_contract`, add `"price_refresh_interval_hours": 12` to `settings_body` and these assertions:

```python
assert update_settings.json()["settings"]["price_refresh_interval_hours"] == 12
assert get_settings.json()["settings"]["price_refresh_interval_hours"] == 12
```

- [ ] **Step 3: Run RED**

Run:

```powershell
rtk py -m pytest tests/unit/test_source_service.py::test_monitor_settings_include_price_refresh_interval_default_and_updates tests/contract/test_admin_api_contract.py::test_admin_source_and_settings_contract -q
```

Expected: tests fail because `price_refresh_interval_hours` is absent from defaults, request schema, or typed response.

- [ ] **Step 4: Implement minimal backend settings support**

In `src/price_monitor/domains/sources/service.py`, add:

```python
DEFAULT_PRICE_REFRESH_INTERVAL_HOURS = 8
DEFAULT_MONITOR_SETTINGS = {
    "max_tracked_products_per_user": "10",
    "price_refresh_interval_hours": str(DEFAULT_PRICE_REFRESH_INTERVAL_HOURS),
    "joom_browser_provider_url": "",
    "joom_browser_provider_token": "",
    "joom_browser_provider_timeout_seconds": "25.0",
    "joom_browser_provider_wait_selector": 'meta[property="product:price:amount"]',
}
```

Add this method inside `SourceService`:

```python
    def effective_fetch_interval_hours(self, source: MonitoredSource) -> int:
        if source.fetch_interval_hours >= 1:
            return source.fetch_interval_hours
        return max(1, int(self.get_settings()["price_refresh_interval_hours"]))
```

In `src/price_monitor/domains/sources/schemas.py`, add to `MonitorSettingsPatchRequest`:

```python
    price_refresh_interval_hours: int | None = Field(default=None, ge=1)
```

In `src/price_monitor/api/v1/admin.py`, add to `_typed_settings()`:

```python
        "price_refresh_interval_hours": int(settings["price_refresh_interval_hours"]),
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/unit/test_source_service.py::test_monitor_settings_include_price_refresh_interval_default_and_updates tests/contract/test_admin_api_contract.py::test_admin_source_and_settings_contract -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
rtk git add src/price_monitor/domains/sources/service.py src/price_monitor/domains/sources/schemas.py src/price_monitor/api/v1/admin.py tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py
rtk git commit -m "feat: add price refresh cadence setting"
```

---

### Task 2: Due Fetch Scheduler Uses Effective Interval

**Files:**
- Create: `src/price_monitor/workers/scheduler.py`
- Modify: `src/price_monitor/domains/watchlist/service.py`
- Test: `tests/unit/test_fetch_scheduler.py`
- Test: `tests/integration/test_watchlist_service.py`

**Interfaces:**
- Consumes: `SourceService.effective_fetch_interval_hours(source: MonitoredSource) -> int`.
- Produces: `schedule_due_fetch_jobs(session: Session, *, now: datetime, limit: int = 100) -> list[FetchJob]`.

- [ ] **Step 1: Write the failing scheduler test**

Create `tests/unit/test_fetch_scheduler.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from price_monitor.domains.products.models import Product
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.models import WatchlistItem
from price_monitor.workers.scheduler import schedule_due_fetch_jobs


def test_schedule_due_fetch_jobs_uses_global_default_when_source_has_default_zero(
    session: Session,
) -> None:
    now = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
    source = SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=1,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )
    source.fetch_interval_hours = 0
    SourceService(session).update_settings({"price_refresh_interval_hours": "8"})
    product = Product(
        source_domain="example.com",
        canonical_url="https://example.com/p/1",
        canonical_url_hash="hash-1",
        last_fetched_at=now - timedelta(hours=8, minutes=1),
    )
    session.add(product)
    session.flush()
    session.add(
        WatchlistItem(
            user_id="wp:test:1",
            product_id=product.id,
            canonical_url_hash=product.canonical_url_hash,
            active_identity_key="wp:test:1:hash-1",
            target_price_minor=None,
            currency="RUB",
            status="active",
        )
    )
    session.flush()

    jobs = schedule_due_fetch_jobs(session, now=now)

    assert len(jobs) == 1
    assert jobs[0].product_id == product.id
    assert jobs[0].logical_key.startswith(f"scheduler:{product.id}:")
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/unit/test_fetch_scheduler.py -q
```

Expected: import fails because `price_monitor.workers.scheduler` does not exist.

- [ ] **Step 3: Implement scheduler**

Create `src/price_monitor/workers/scheduler.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import FetchJob
from price_monitor.domains.sources.models import MonitoredSource
from price_monitor.domains.sources.service import SourceService
from price_monitor.domains.watchlist.models import WatchlistItem


def schedule_due_fetch_jobs(
    session: Session,
    *,
    now: datetime,
    limit: int = 100,
) -> list[FetchJob]:
    source_service = SourceService(session)
    rows = session.execute(
        select(WatchlistItem, Product, MonitoredSource)
        .join(Product, WatchlistItem.product_id == Product.id)
        .join(MonitoredSource, Product.source_domain == MonitoredSource.source_domain)
        .where(WatchlistItem.status == "active", MonitoredSource.status == "active")
        .order_by(WatchlistItem.updated_at.asc(), WatchlistItem.id.asc())
        .limit(limit)
    ).all()

    jobs: list[FetchJob] = []
    for item, product, source in rows:
        interval = source_service.effective_fetch_interval_hours(source)
        due_at = now - timedelta(hours=interval)
        if product.last_fetched_at is not None and product.last_fetched_at > due_at:
            continue
        logical_key = f"scheduler:{product.id}:{now.isoformat()}"
        existing = session.scalar(select(FetchJob).where(FetchJob.logical_key == logical_key))
        if existing is not None:
            jobs.append(existing)
            continue
        job = FetchJob(
            product_id=product.id,
            logical_key=logical_key,
            status="queued",
            scheduled_for=now,
        )
        session.add(job)
        jobs.append(job)
    session.flush()
    return jobs
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/unit/test_fetch_scheduler.py -q
```

Expected: test passes.

- [ ] **Step 5: Add source override test**

Add a second test in `tests/unit/test_fetch_scheduler.py` that sets `source.fetch_interval_hours = 2`, `price_refresh_interval_hours = 8`, and `last_fetched_at = now - timedelta(hours=2, minutes=1)`, then asserts one job is scheduled.

Run:

```powershell
rtk py -m pytest tests/unit/test_fetch_scheduler.py -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
rtk git add src/price_monitor/workers/scheduler.py tests/unit/test_fetch_scheduler.py
rtk git commit -m "feat: schedule due price refresh jobs"
```

---

### Task 3: Store Product URL Classifier

**Files:**
- Create: `src/price_monitor/domains/sources/classification.py`
- Modify: `src/price_monitor/domains/sources/service.py`
- Modify: `src/price_monitor/api/v1/sources.py`
- Test: `tests/unit/test_product_url_classifier.py`
- Test: `tests/contract/test_api_contract.py`

**Interfaces:**
- Produces: `ProductUrlClassification` dataclass and `classify_product_url(raw_url: str) -> ProductUrlClassification`.
- Produces stable error codes: `unsupported_store`, `monitoring_unavailable`, `not_product_url`, `unsafe_url`, `source_product_id_missing`, `source_url_pattern_unsupported`.

- [ ] **Step 1: Write classifier tests**

Create `tests/unit/test_product_url_classifier.py`:

```python
import pytest

from price_monitor.domains.sources.classification import classify_product_url


@pytest.mark.parametrize(
    ("url", "domain", "source_product_id"),
    (
        ("https://www.aliexpress.com/item/1005001112223334.html", "aliexpress.com", "1005001112223334"),
        ("https://www.citilink.ru/product/router-wifi-123456/", "citilink.ru", "123456"),
        ("https://www.joom.com/ru/products/64f1abcd1234567890abcdef", "joom.com", "64f1abcd1234567890abcdef"),
        ("https://www.wildberries.ru/catalog/123456789/detail.aspx", "wildberries.ru", "123456789"),
        ("https://www.ozon.ru/product/example-123456789/", "ozon.ru", "123456789"),
        ("https://market.yandex.ru/product--phone/123456789", "market.yandex.ru", "123456789"),
    ),
)
def test_required_store_product_urls_are_classified(
    url: str,
    domain: str,
    source_product_id: str,
) -> None:
    result = classify_product_url(url)

    assert result.is_product_url is True
    assert result.source_domain == domain
    assert result.source_product_id == source_product_id
    assert result.error_code is None


@pytest.mark.parametrize(
    ("url", "error_code"),
    (
        ("https://www.aliexpress.com/wholesale?SearchText=phone", "not_product_url"),
        ("https://www.citilink.ru/catalog/smartfony/", "not_product_url"),
        ("https://www.joom.com/ru/search/q.phone", "not_product_url"),
        ("https://www.wildberries.ru/catalog/0/search.aspx?search=phone", "not_product_url"),
        ("https://www.ozon.ru/category/smartfony-15502/", "not_product_url"),
        ("https://market.yandex.ru/search?text=phone", "not_product_url"),
        ("http://127.0.0.1/product/1", "unsafe_url"),
    ),
)
def test_non_product_and_unsafe_urls_get_stable_errors(url: str, error_code: str) -> None:
    result = classify_product_url(url)

    assert result.is_product_url is False
    assert result.error_code == error_code
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/unit/test_product_url_classifier.py -q
```

Expected: import fails because `classification.py` does not exist.

- [ ] **Step 3: Implement classifier**

Create `src/price_monitor/domains/sources/classification.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from price_monitor.core.url_policy import UnsafeUrlError, validate_public_product_url


@dataclass(frozen=True)
class ProductUrlClassification:
    source_domain: str | None
    canonical_url: str | None
    canonical_url_hash: str | None
    source_product_id: str | None
    is_product_url: bool
    error_code: str | None
    message: str


STORE_ROOTS = {
    "aliexpress.com": re.compile(r"/item/(\d+)\.html/?$", re.IGNORECASE),
    "citilink.ru": re.compile(r"-(\d+)/?$", re.IGNORECASE),
    "joom.com": re.compile(r"/products/([A-Za-z0-9_-]+)/?$", re.IGNORECASE),
    "wildberries.ru": re.compile(r"/catalog/(\d+)/detail\.aspx/?$", re.IGNORECASE),
    "ozon.ru": re.compile(r"/product/.+?-(\d+)/?$", re.IGNORECASE),
    "market.yandex.ru": re.compile(r"/(?:product--[^/]+|product|model)/(\d+)", re.IGNORECASE),
}


def classify_product_url(raw_url: str) -> ProductUrlClassification:
    try:
        validated = validate_public_product_url(raw_url)
    except UnsafeUrlError as exc:
        return ProductUrlClassification(None, None, None, None, False, "unsafe_url", str(exc))

    parsed = urlsplit(validated.canonical_url)
    host = validated.source_domain
    source_domain = _store_root(host)
    if source_domain is None:
        return ProductUrlClassification(
            host,
            validated.canonical_url,
            validated.canonical_url_hash,
            None,
            False,
            "unsupported_store",
            "Магазин не поддерживается",
        )

    match = STORE_ROOTS[source_domain].search(parsed.path)
    if match is None:
        return ProductUrlClassification(
            source_domain,
            validated.canonical_url,
            validated.canonical_url_hash,
            None,
            False,
            "not_product_url",
            "Укажите ссылку на карточку товара.",
        )

    source_product_id = match.group(1)
    return ProductUrlClassification(
        source_domain,
        validated.canonical_url,
        validated.canonical_url_hash,
        source_product_id,
        True,
        None,
        "",
    )


def _store_root(hostname: str) -> str | None:
    for root in STORE_ROOTS:
        if hostname == root or hostname.endswith(f".{root}"):
            return root
    return None
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/unit/test_product_url_classifier.py -q
```

Expected: classifier tests pass.

- [ ] **Step 5: Integrate supported-source API**

Modify `src/price_monitor/api/v1/sources.py` so `supported_source()` calls `classify_product_url(url)` first. Return the classifier error payload for `unsafe_url` and `not_product_url`, then keep existing paused/disabled source handling.

Run:

```powershell
rtk py -m pytest tests/contract/test_api_contract.py tests/contract/test_admin_api_contract.py -q
```

Expected: contracts pass after updating expected error payloads for non-product URLs.

- [ ] **Step 6: Commit**

Run:

```powershell
rtk git add src/price_monitor/domains/sources/classification.py src/price_monitor/api/v1/sources.py tests/unit/test_product_url_classifier.py tests/contract/test_api_contract.py
rtk git commit -m "feat: classify marketplace product urls"
```

---

### Task 4: Watchlist Rejects Non-Product URLs Before Product Creation

**Files:**
- Modify: `src/price_monitor/domains/products/models.py`
- Modify: `src/price_monitor/domains/watchlist/service.py`
- Test: `tests/integration/test_watchlist_service.py`
- Test: `tests/contract/test_api_contract.py`

**Interfaces:**
- Consumes: `classify_product_url(raw_url: str) -> ProductUrlClassification`.
- Produces: `Product.source_product_id: str | None`.

- [ ] **Step 1: Write failing watchlist test**

Add to `tests/integration/test_watchlist_service.py`:

```python
def test_add_item_rejects_supported_store_non_product_url(session: Session) -> None:
    service = SourceService(session)
    service.upsert_source(
        MonitoredSourceInput(
            source_domain="ozon.ru",
            display_name="Ozon",
            logo_url="https://ozon.ru/logo.png",
            status="active",
            fetch_interval_hours=8,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    result = WatchlistService(session).add_item(
        user_id="wp:test:1",
        product_url="https://www.ozon.ru/category/smartfony-15502/",
        target_price_minor=None,
        currency="RUB",
        request_id="req-non-product",
    )

    assert result.item is None
    assert result.error_code == "not_product_url"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/integration/test_watchlist_service.py::test_add_item_rejects_supported_store_non_product_url -q
```

Expected: test fails because current `WatchlistService.add_item()` accepts supported domains without product-path classification.

- [ ] **Step 3: Implement product classification in watchlist**

In `src/price_monitor/domains/products/models.py`, add:

```python
    source_product_id: Mapped[str | None] = mapped_column(String(128), index=True)
```

In `src/price_monitor/domains/watchlist/service.py`, before duplicate checks:

```python
        classification = classify_product_url(product_url)
        if not classification.is_product_url:
            return WatchlistAddResult(
                item=None,
                created=False,
                error_code=classification.error_code or "not_product_url",
            )
```

Update `_get_or_create_product()` to accept `source_product_id: str | None` and assign:

```python
        product.source_product_id = source_product_id
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/integration/test_watchlist_service.py::test_add_item_rejects_supported_store_non_product_url tests/contract/test_api_contract.py -q
```

Expected: watchlist and API contracts pass.

- [ ] **Step 5: Commit**

Run:

```powershell
rtk git add src/price_monitor/domains/products/models.py src/price_monitor/domains/watchlist/service.py tests/integration/test_watchlist_service.py tests/contract/test_api_contract.py
rtk git commit -m "feat: reject non-product watchlist urls"
```

---

### Task 5: Adapter Interface, Registry, And Safe Extraction Metadata

**Files:**
- Modify: `src/price_monitor/domains/fetching/ports.py`
- Create: `src/price_monitor/domains/fetching/sources/base.py`
- Create: `src/price_monitor/domains/fetching/sources/registry.py`
- Create: `src/price_monitor/domains/fetching/sources/generic_html.py`
- Modify: `src/price_monitor/domains/fetching/extraction.py`
- Test: `tests/unit/test_source_adapters.py`

**Interfaces:**
- Produces: `ProductExtraction`, `SourceFetchResult`, `FetchContext`, `SourceAdapter`.
- Produces: `get_adapter_for_source(source_domain: str) -> SourceAdapter`.

- [ ] **Step 1: Write failing adapter test**

Create `tests/unit/test_source_adapters.py`:

```python
from decimal import Decimal

from price_monitor.domains.fetching.ports import FetchPageResult
from price_monitor.domains.fetching.sources.base import FetchContext
from price_monitor.domains.fetching.sources.registry import get_adapter_for_source


class StaticFetcher:
    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        return FetchPageResult(
            content=(
                '<script type="application/ld+json">'
                '{"@type":"Product","name":"Phone","image":"https://img.test/p.jpg",'
                '"offers":{"price":"123.45","priceCurrency":"RUB"},'
                '"aggregateRating":{"ratingValue":"4.8"}}'
                "</script>"
            ),
            final_url=url,
            http_status=200,
            response_ms=15,
        )


def test_generic_adapter_returns_confident_extraction() -> None:
    adapter = get_adapter_for_source("example.com")
    result = adapter.fetch_product(
        FetchContext(
            canonical_url="https://example.com/p/1",
            source_domain="example.com",
            source_product_id=None,
            strategy="direct_http",
            fetcher=StaticFetcher(),
            proxy_url=None,
            fallback_currency="RUB",
        )
    )

    assert result.status == "ok"
    assert result.extraction is not None
    assert result.extraction.title == "Phone"
    assert result.extraction.price_minor == 12345
    assert result.extraction.confidence == Decimal("0.90")
    assert result.parser_version == "generic-html-v1"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/unit/test_source_adapters.py -q
```

Expected: import fails because adapter modules do not exist.

- [ ] **Step 3: Implement shared adapter types**

Add to `src/price_monitor/domains/fetching/ports.py`:

```python
from decimal import Decimal


@dataclass(frozen=True)
class ProductExtraction:
    title: str
    price_minor: int
    currency: str
    image_url: str | None
    rating_value: str | None
    availability: str | None
    canonical_url: str
    source_product_id: str | None
    parser_version: str
    confidence: Decimal
```

Create `src/price_monitor/domains/fetching/sources/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from price_monitor.domains.fetching.ports import ProductExtraction, ProductPageFetcher


@dataclass(frozen=True)
class FetchContext:
    canonical_url: str
    source_domain: str
    source_product_id: str | None
    strategy: str
    fetcher: ProductPageFetcher
    proxy_url: str | None
    fallback_currency: str


@dataclass(frozen=True)
class SourceFetchResult:
    status: str
    extraction: ProductExtraction | None
    http_status: int | None
    response_ms: int | None
    reason: str | None
    block_reason: str | None
    challenge_detected: bool
    parser_version: str | None
    parser_confidence: str | None


class SourceAdapter(Protocol):
    source_domain: str

    def fetch_product(self, context: FetchContext) -> SourceFetchResult:
        ...
```

- [ ] **Step 4: Implement generic adapter and registry**

Create `src/price_monitor/domains/fetching/sources/generic_html.py` with a `GenericHtmlAdapter` that calls `context.fetcher.fetch()` and converts `extract_product_data()` into `ProductExtraction` with parser version `generic-html-v1` and confidence `Decimal("0.90")`.

Create `src/price_monitor/domains/fetching/sources/registry.py`:

```python
from __future__ import annotations

from price_monitor.domains.fetching.sources.base import SourceAdapter
from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


_GENERIC = GenericHtmlAdapter()


def get_adapter_for_source(source_domain: str) -> SourceAdapter:
    return _GENERIC
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/unit/test_source_adapters.py -q
```

Expected: adapter test passes.

- [ ] **Step 6: Commit**

Run:

```powershell
rtk git add src/price_monitor/domains/fetching/ports.py src/price_monitor/domains/fetching/sources tests/unit/test_source_adapters.py
rtk git commit -m "feat: add source adapter registry"
```

---

### Task 6: Fetch Pipeline Lifecycle, Metadata, And Confidence Gate

**Files:**
- Modify: `src/price_monitor/domains/reliability/models.py`
- Modify: `src/price_monitor/domains/fetching/service.py`
- Modify: `src/price_monitor/workers/tasks/fetch_product.py`
- Test: `tests/unit/test_fetch_pipeline.py`

**Interfaces:**
- Consumes: `get_adapter_for_source(source_domain: str) -> SourceAdapter`.
- Produces terminal job statuses `ok`, `failed`, `quarantined`, `dead_letter` with `status_reason`, `started_at`, `finished_at`, and `attempt_count`.

- [ ] **Step 1: Write failing lifecycle test**

Add to `tests/unit/test_fetch_pipeline.py`:

```python
def test_fetch_pipeline_records_parser_metadata_and_blocks_low_confidence(session: Session) -> None:
    now = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
    source = MonitoredSource(
        source_domain="example.com",
        display_name="Example",
        logo_url="https://example.com/logo.png",
        status="active",
        fetch_interval_hours=8,
        history_retention_days=90,
        browser_fallback_allowed=False,
    )
    product = Product(
        source_domain="example.com",
        canonical_url="https://example.com/p/1",
        canonical_url_hash="hash-1",
        currency="RUB",
    )
    session.add_all([source, product])
    session.flush()

    result = FetchPipeline(session, direct_fetcher=LowConfidenceFetcher()).run(
        product.id,
        now=now,
    )
    attempt = session.query(FetchAttempt).one()

    assert result.status == "low_confidence"
    assert attempt.reason == "low_confidence"
    assert attempt.parser_version == "generic-html-v1"
    assert attempt.parser_confidence == "0.40"
    assert session.query(PricePoint).count() == 0
```

Add `LowConfidenceFetcher` in the same test file:

```python
class LowConfidenceFetcher:
    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        return FetchPageResult(
            content='<meta property="og:title" content="Weak"><meta name="price" content="1.00">',
            final_url=url,
            http_status=200,
            response_ms=5,
        )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/unit/test_fetch_pipeline.py::test_fetch_pipeline_records_parser_metadata_and_blocks_low_confidence -q
```

Expected: test fails because `FetchAttempt` lacks parser metadata and the pipeline does not apply confidence gating.

- [ ] **Step 3: Add model fields**

In `src/price_monitor/domains/reliability/models.py`, add fields to `FetchJob`:

```python
    status_reason: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

Add fields to `FetchAttempt`:

```python
    provider_name: Mapped[str | None] = mapped_column(String(64))
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    provider_cost_minor: Mapped[int | None] = mapped_column(Integer)
    rendered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_reason: Mapped[str | None] = mapped_column(String(255))
    challenge_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parser_version: Mapped[str | None] = mapped_column(String(64))
    parser_confidence: Mapped[str | None] = mapped_column(String(16))
```

- [ ] **Step 4: Update pipeline**

In `src/price_monitor/domains/fetching/service.py`, route each strategy through `get_adapter_for_source(product.source_domain)`, copy result metadata into `FetchAttempt`, and write product/price only when confidence is at least `Decimal("0.70")`.

Use this status assignment inside the attempt loop:

```python
            attempt.parser_version = result.parser_version
            attempt.parser_confidence = result.parser_confidence
            attempt.block_reason = result.block_reason
            attempt.challenge_detected = result.challenge_detected
            attempt.http_status = result.http_status
            attempt.response_ms = result.response_ms
            if result.status != "ok" or result.extraction is None:
                attempt.reason = result.reason or result.status
                terminal_status = attempt.reason
                self._session.flush()
                continue
```

- [ ] **Step 5: Update worker job lifecycle**

In `src/price_monitor/workers/tasks/fetch_product.py`, set:

```python
        if job is not None:
            job.status = "running"
            job.started_at = datetime.now(UTC)
            job.attempt_count += 1
            session.flush()
```

After `FetchPipeline.run()`:

```python
        if job is not None:
            job.status = "ok" if result.status == "ok" else "failed"
            job.status_reason = None if result.status == "ok" else result.status
            job.finished_at = datetime.now(UTC)
            session.flush()
```

Wrap unexpected exceptions so the job is marked `dead_letter` with `status_reason = type(exc).__name__` before re-raising.

- [ ] **Step 6: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/unit/test_fetch_pipeline.py -q
```

Expected: fetch pipeline tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
rtk git add src/price_monitor/domains/reliability/models.py src/price_monitor/domains/fetching/service.py src/price_monitor/workers/tasks/fetch_product.py tests/unit/test_fetch_pipeline.py
rtk git commit -m "feat: record fetch lifecycle diagnostics"
```

---

### Task 7: Required Store Adapters With Sanitized Fixtures

**Files:**
- Create: `src/price_monitor/domains/fetching/sources/aliexpress.py`
- Create: `src/price_monitor/domains/fetching/sources/citilink.py`
- Create: `src/price_monitor/domains/fetching/sources/joom.py`
- Create: `src/price_monitor/domains/fetching/sources/wildberries.py`
- Create: `src/price_monitor/domains/fetching/sources/ozon.py`
- Create: `src/price_monitor/domains/fetching/sources/yandex_market.py`
- Modify: `src/price_monitor/domains/fetching/sources/registry.py`
- Test: `tests/unit/test_source_adapters.py`

**Interfaces:**
- Consumes: `GenericHtmlAdapter` and `SourceFetchResult`.
- Produces source-specific parser versions: `aliexpress-v1`, `citilink-v1`, `joom-v1`, `wildberries-v1`, `ozon-v1`, `yandex-market-v1`.

- [ ] **Step 1: Write failing required-store adapter tests**

Add to `tests/unit/test_source_adapters.py`:

```python
import pytest


@pytest.mark.parametrize(
    ("source_domain", "parser_version"),
    (
        ("aliexpress.com", "aliexpress-v1"),
        ("citilink.ru", "citilink-v1"),
        ("joom.com", "joom-v1"),
        ("wildberries.ru", "wildberries-v1"),
        ("ozon.ru", "ozon-v1"),
        ("market.yandex.ru", "yandex-market-v1"),
    ),
)
def test_required_store_adapters_extract_fixture_product(
    source_domain: str,
    parser_version: str,
) -> None:
    adapter = get_adapter_for_source(source_domain)
    result = adapter.fetch_product(
        FetchContext(
            canonical_url=f"https://{source_domain}/fixture-product",
            source_domain=source_domain,
            source_product_id="123456789",
            strategy="direct_http",
            fetcher=StaticFetcher(),
            proxy_url=None,
            fallback_currency="RUB",
        )
    )

    assert result.status == "ok"
    assert result.extraction is not None
    assert result.extraction.title == "Phone"
    assert result.extraction.price_minor == 12345
    assert result.parser_version == parser_version
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/unit/test_source_adapters.py::test_required_store_adapters_extract_fixture_product -q
```

Expected: test fails because registry returns the generic parser version for required stores.

- [ ] **Step 3: Implement adapter classes**

For each required adapter file, subclass the generic behavior and override `source_domain` and `parser_version`.

Example for `src/price_monitor/domains/fetching/sources/citilink.py`:

```python
from __future__ import annotations

from price_monitor.domains.fetching.sources.generic_html import GenericHtmlAdapter


class CitilinkAdapter(GenericHtmlAdapter):
    source_domain = "citilink.ru"
    parser_version = "citilink-v1"
```

Create the same class shape for:

- `AliExpressAdapter`, `source_domain = "aliexpress.com"`, `parser_version = "aliexpress-v1"`;
- `JoomAdapter`, `source_domain = "joom.com"`, `parser_version = "joom-v1"`;
- `WildberriesAdapter`, `source_domain = "wildberries.ru"`, `parser_version = "wildberries-v1"`;
- `OzonAdapter`, `source_domain = "ozon.ru"`, `parser_version = "ozon-v1"`;
- `YandexMarketAdapter`, `source_domain = "market.yandex.ru"`, `parser_version = "yandex-market-v1"`.

- [ ] **Step 4: Register required adapters**

In `src/price_monitor/domains/fetching/sources/registry.py`, use:

```python
_ADAPTERS = {
    "aliexpress.com": AliExpressAdapter(),
    "citilink.ru": CitilinkAdapter(),
    "joom.com": JoomAdapter(),
    "wildberries.ru": WildberriesAdapter(),
    "ozon.ru": OzonAdapter(),
    "market.yandex.ru": YandexMarketAdapter(),
}
```

`get_adapter_for_source()` returns `_ADAPTERS.get(source_domain, _GENERIC)`.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/unit/test_source_adapters.py tests/unit/test_fetch_pipeline.py -q
```

Expected: adapter and pipeline tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
rtk git add src/price_monitor/domains/fetching/sources tests/unit/test_source_adapters.py
rtk git commit -m "feat: add required marketplace adapters"
```

---

### Task 8: Product Detail Diagnostics And Single Empty Chart State

**Files:**
- Modify: `src/price_monitor/api/v1/products.py`
- Modify: `src/price_monitor/api/v1/price_history.py`
- Test: `tests/contract/test_product_card_contract.py`

**Interfaces:**
- Consumes: `FetchJob` and `FetchAttempt` metadata fields.
- Produces `latest_fetch` response object under `GET /api/v1/products/{product_id}`.

- [ ] **Step 1: Write failing product contract assertions**

In `tests/contract/test_product_card_contract.py`, add assertions that product detail returns:

```python
assert body["latest_fetch"]["status"] == "failed"
assert body["latest_fetch"]["reason"] == "captcha_detected"
assert body["latest_fetch"]["strategy"] == "direct_http"
assert body["latest_fetch"]["parser_version"] == "citilink-v1"
assert body["latest_fetch"]["parser_confidence"] == "0.90"
```

For empty chart state, assert:

```python
assert chart_body["points"] == []
assert chart_body["summary"] == {
    "lowest_price_minor": None,
    "latest_price_minor": None,
}
assert chart_body["currency"] is None
```

- [ ] **Step 2: Run RED**

Run:

```powershell
rtk py -m pytest tests/contract/test_product_card_contract.py -q
```

Expected: product detail lacks `latest_fetch` metadata or empty chart currency differs.

- [ ] **Step 3: Implement product latest fetch summary**

In `src/price_monitor/api/v1/products.py`, query latest job and attempt for the product and add:

```python
        "latest_fetch": {
            "status": latest_job.status if latest_job is not None else product.last_fetch_status,
            "reason": latest_attempt.reason if latest_attempt is not None else None,
            "strategy": latest_attempt.strategy if latest_attempt is not None else None,
            "provider_name": latest_attempt.provider_name if latest_attempt is not None else None,
            "block_reason": latest_attempt.block_reason if latest_attempt is not None else None,
            "challenge_detected": latest_attempt.challenge_detected if latest_attempt is not None else False,
            "parser_version": latest_attempt.parser_version if latest_attempt is not None else None,
            "parser_confidence": latest_attempt.parser_confidence if latest_attempt is not None else None,
            "started_at": latest_job.started_at.isoformat() if latest_job and latest_job.started_at else None,
            "finished_at": latest_job.finished_at.isoformat() if latest_job and latest_job.finished_at else None,
        },
```

In `src/price_monitor/api/v1/price_history.py`, keep `currency: currency or product.currency` only when product currency is set; otherwise return `None`.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
rtk py -m pytest tests/contract/test_product_card_contract.py -q
```

Expected: contract test passes.

- [ ] **Step 5: Commit**

Run:

```powershell
rtk git add src/price_monitor/api/v1/products.py src/price_monitor/api/v1/price_history.py tests/contract/test_product_card_contract.py
rtk git commit -m "feat: expose safe fetch diagnostics"
```

---

### Task 9: WordPress Admin Cadence Setting And Account Error Copy

**Files:**
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\admin\class-cashback-price-monitor-admin.php`
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\development\test\tests\PriceMonitorAdminTest.php`
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\includes\price-monitor\class-cashback-price-monitor-rest-controller.php`
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\development\test\tests\PriceMonitorRestControllerTest.php`
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\assets\js\price-monitor-account.js`
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\tests\price-monitor-account.test.mjs`

**Interfaces:**
- Consumes: backend admin setting `price_refresh_interval_hours`.
- Produces: admin field `name="price_refresh_interval_hours"` with default `8`, min `1`, and backend PATCH payload.
- Produces frontend copy for `not_product_url`, `unsafe_url`, `source_product_id_missing`, and `source_url_pattern_unsupported`.

- [ ] **Step 1: Check plugin status before editing**

Run:

```powershell
rtk git -C F:\wamp64\www\kash-back\wp-content\plugins\cash-back status --short --branch
```

Expected: note any existing modified files and keep them.

- [ ] **Step 2: Write failing admin test**

In `PriceMonitorAdminTest.php`, update `spy_client()` settings response to include:

```php
'price_refresh_interval_hours' => 8,
```

In `test_monitoring_settings_page_contains_store_logo_and_provider_fields()`, add:

```php
self::assertStringContainsString( 'name="price_refresh_interval_hours"', $html );
self::assertStringContainsString( 'Частота обновления цены, часов', $html );
```

In `test_settings_backend_url_is_sanitized_and_secret_is_redacted_in_rendered_html()`, post:

```php
'price_refresh_interval_hours' => '8',
```

and assert backend payload:

```php
self::assertSame(
    array(
        'max_tracked_products_per_user' => 25,
        'price_refresh_interval_hours'  => 8,
    ),
    $calls[0]['payload']
);
```

- [ ] **Step 3: Run WordPress RED**

Run in plugin checkout:

```powershell
rtk development/test/vendor/bin/phpunit.bat --filter PriceMonitorAdminTest
```

Expected: test fails because the field is not rendered or saved.

- [ ] **Step 4: Implement admin field**

In `class-cashback-price-monitor-admin.php`, read remote setting near `$user_limit`:

```php
$price_refresh_interval_hours = isset( $remote_settings['price_refresh_interval_hours'] )
    ? (int) $remote_settings['price_refresh_interval_hours']
    : 8;
```

Render a row in the backend settings form:

```php
<tr>
    <th scope="row"><label for="cashback-price-monitor-refresh-interval"><?php echo esc_html( 'Частота обновления цены, часов' ); ?></label></th>
    <td>
        <input
            id="cashback-price-monitor-refresh-interval"
            type="number"
            min="1"
            name="price_refresh_interval_hours"
            class="small-text"
            value="<?php echo esc_attr( (string) $price_refresh_interval_hours ); ?>"
        />
    </td>
</tr>
```

In `handle_save_settings()`, include:

```php
'price_refresh_interval_hours' => $this->sanitize_positive_int( $this->post_value( 'price_refresh_interval_hours', 8 ), 8 ),
```

Add to `$backend_payload`:

```php
'price_refresh_interval_hours' => $payload['price_refresh_interval_hours'],
```

- [ ] **Step 5: Run admin GREEN**

Run in plugin checkout:

```powershell
rtk development/test/vendor/bin/phpunit.bat --filter PriceMonitorAdminTest
```

Expected: admin tests pass.

- [ ] **Step 6: Write and implement account error copy**

In `tests/price-monitor-account.test.mjs`, add a case where POST `/items` rejects with `{ code: 'not_product_url', message: 'Укажите ссылку на карточку товара.' }` and assert the feedback contains that message.

In `assets/js/price-monitor-account.js`, extend `messages`:

```javascript
not_product_url: text('notProductUrl', 'Укажите ссылку на карточку товара.'),
unsafe_url: text('unsafeUrl', 'Ссылка небезопасна или недоступна для проверки.'),
source_product_id_missing: text('sourceProductIdMissing', 'Не удалось определить товар по ссылке.'),
source_url_pattern_unsupported: text('sourceUrlPatternUnsupported', 'Формат ссылки пока не поддерживается.')
```

Run:

```powershell
rtk node --test tests/price-monitor-account.test.mjs
```

Expected: JS tests pass.

- [ ] **Step 7: Commit plugin changes**

Run:

```powershell
rtk git -C F:\wamp64\www\kash-back\wp-content\plugins\cash-back add admin/class-cashback-price-monitor-admin.php development/test/tests/PriceMonitorAdminTest.php includes/price-monitor/class-cashback-price-monitor-rest-controller.php development/test/tests/PriceMonitorRestControllerTest.php assets/js/price-monitor-account.js tests/price-monitor-account.test.mjs
rtk git -C F:\wamp64\www\kash-back\wp-content\plugins\cash-back commit -m "feat: add price monitor refresh cadence setting"
```

---

### Task 10: Full Local Gates, Test Deploy, And Frontend Smoke

**Files:**
- Modify only files required by failures discovered in this task.

**Interfaces:**
- Consumes all previous tasks.
- Produces final evidence: backend commit hash, plugin commit hash, GitHub Actions URL, server SHA, store-by-store smoke result, test user id/email, and cleanup command.

- [ ] **Step 1: Run backend local gates**

Run in `F:\cash-back\monitor_cashback`:

```powershell
rtk py -m pytest -q
rtk ruff check .
rtk ruff format --check .
rtk mypy
rtk py -m pip check
rtk docker compose config --quiet
rtk git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 2: Run plugin local gates**

Run in `F:\wamp64\www\kash-back\wp-content\plugins\cash-back`:

```powershell
rtk vendor/bin/phpcs.bat
rtk vendor/bin/phpstan.bat
rtk development/test/vendor/bin/phpunit.bat
rtk node --test
rtk git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 3: Push backend develop and verify Actions**

Run:

```powershell
rtk git status --short --branch
rtk git push origin develop
rtk gh run list --branch develop --limit 5
```

Expected: newest workflow for pushed SHA reaches success for `secret-scan`, `quality`, and `deploy-test`.

- [ ] **Step 4: Read-only server verification**

Run the existing project SSH/deploy verification commands from `docs/deploy.md` without editing production files. Capture:

- release SHA under `/home/igor/monitor_cashback/current`;
- `/health/live`;
- `/health/ready`;
- `docker compose ps`;
- API and worker logs for the smoke window.

Expected: deployed SHA matches pushed backend commit and logs have no traceback/error/critical during smoke.

- [ ] **Step 5: Frontend smoke with one temporary user**

Create one temporary WordPress user, record id/email, log in, and open `/account/price-monitor`.

For each required store, run:

- add one valid individual product URL;
- verify product card title, image, current price, optional rating, price chart, and loading/error state;
- add one non-product URL and verify clear Russian error copy.

If AliExpress, Joom, Ozon, Wildberries, or Yandex Market reaches a provider-required state after three source-specific attempts, stop that store and report `"Нужно подключение Decodo"` with the credential or activation needed.

- [ ] **Step 6: Final report**

Report:

- backend changes and backend commit hash;
- plugin changes and plugin commit hash;
- GitHub Actions URL and result;
- server SHA and health/log evidence;
- store-by-store working or blocked status;
- frontend evidence paths or screenshot names without secrets;
- temporary user id/email and deletion command;
- explicit non-goals.
