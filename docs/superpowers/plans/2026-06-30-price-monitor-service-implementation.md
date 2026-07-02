# Price Monitor Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved production-ready price-monitor vertical slice across the FastAPI backend and WordPress plugin.

**Architecture:** The backend owns monitoring state, product data, fetch jobs, price history, alerts, and source health. WordPress owns admin/account UI, browser auth, email delivery, cashback activation UX, and HMAC proxying to the backend. Browser requests never call backend internals directly.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Alembic, Celery, PostgreSQL, Redis, RabbitMQ, pytest, ruff, mypy, WordPress PHP 8.3 plugin code, PHPUnit, PHPCS, vanilla JavaScript.

## Global Constraints

- Always run shell commands with `rtk`.
- Backend implementation branch starts from `develop` in `F:\cash-back\monitor_cashback`.
- WordPress implementation branch starts from `main` in `F:\wamp64\www\kash-back\wp-content\plugins\cash-back`.
- Use RED -> GREEN TDD for behavior changes.
- Do not store marketplace passwords, unapproved raw cookies, raw browser
  session captures, provider secrets, proxy credentials, or challenge tokens.
  Source-specific public product fetching may use managed unblocker APIs,
  browser rendering, proxy rotation, and challenge-aware adapters when approved
  for the monitored source.
- Browser requests go through WordPress REST endpoints; WordPress signs backend requests.
- Mutating backend endpoints require HMAC and idempotency.
- Browser-facing WordPress endpoints require REST nonce and user/capability checks.
- Default max tracked products per user is 10.
- Deleted watches allow re-add; active duplicate watches return `duplicate_watchlist_item`.
- Unsupported stores return `unsupported_store` and show `Магазин не поддерживается`.
- Product/history retention after last active watch deletion is 90 days by default.
- Existing cashback activation logic must be reused, not copied.
- Deployment proof must include migrations, health checks, source setup, add product, duplicate rejection, limit enforcement, product fetch, price chart, alert dispatch, delete, and retention behavior.

---

## File Structure

Backend files to create:

- `src/price_monitor/api/v1/admin.py` - HMAC-protected admin endpoints for monitor settings, sources, proxy pools, and diagnostics.
- `src/price_monitor/domains/sources/service.py` - source allowlist, source matching, source settings, proxy policy service.
- `src/price_monitor/domains/sources/schemas.py` - source/proxy request and response DTOs.
- `src/price_monitor/domains/fetching/__init__.py` - fetching domain package.
- `src/price_monitor/domains/fetching/ports.py` - fetcher interfaces and typed result/error objects.
- `src/price_monitor/domains/fetching/extraction.py` - structured product extraction from public HTML.
- `src/price_monitor/domains/fetching/service.py` - fetch job runner and staged strategy selection.
- `src/price_monitor/domains/notifications/service.py` - desired-price alert evaluation and dispatch outbox.
- `tests/unit/test_source_service.py` - source allowlist and proxy policy tests.
- `tests/unit/test_fetch_extraction.py` - structured extraction tests.
- `tests/unit/test_fetch_pipeline.py` - fake fetcher/proxy/browser strategy tests.
- `tests/unit/test_notification_service.py` - alert threshold/dedup/cooldown tests.
- `tests/contract/test_admin_api_contract.py` - backend admin API contract tests.
- `tests/contract/test_product_card_contract.py` - product card/chart contract tests.
- `migrations/versions/20260630_0002_price_monitor_vertical_slice.py` - schema migration.

Backend files to modify:

- `src/price_monitor/main.py` - include new admin router.
- `src/price_monitor/db/models.py` - register new SQLAlchemy models.
- `src/price_monitor/domains/sources/models.py` - add monitored source and proxy models.
- `src/price_monitor/domains/products/models.py` - add product card fields.
- `src/price_monitor/domains/pricing/models.py` - link price points to fetch attempts.
- `src/price_monitor/domains/watchlist/models.py` - support active duplicate key and deleted re-add.
- `src/price_monitor/domains/watchlist/service.py` - enforce source allowlist, limits, duplicate semantics, immediate fetch scheduling.
- `src/price_monitor/api/v1/watchlist.py` - secure read/update flows and stable errors.
- `src/price_monitor/api/v1/products.py` - product card response.
- `src/price_monitor/api/v1/price_history.py` - chart response.
- `src/price_monitor/api/v1/sources.py` - supported-source lookup.
- `src/price_monitor/workers/tasks/fetch_product.py` - run fetch pipeline.
- `tests/contract/test_api_contract.py` - OpenAPI contract updates.
- `tests/integration/test_watchlist_service.py` - watchlist behavior updates.

WordPress files to create:

- `includes/price-monitor/class-cashback-price-monitor-client.php` - backend HMAC client.
- `includes/price-monitor/class-cashback-price-monitor-rest-controller.php` - account REST proxy endpoints.
- `includes/price-monitor/class-cashback-price-monitor-account.php` - WooCommerce account endpoint.
- `admin/class-cashback-price-monitor-admin.php` - admin page and settings save handlers.
- `assets/js/price-monitor-account.js` - account card UI behavior.
- `assets/css/price-monitor-account.css` - account page styling on top of shared account base.
- `assets/js/price-monitor-admin.js` - admin source/proxy form behavior.
- `assets/css/price-monitor-admin.css` - admin diagnostics and source table styling.
- `development/test/tests/PriceMonitorClientTest.php` - backend client signing tests.
- `development/test/tests/PriceMonitorRestControllerTest.php` - REST nonce/permission/proxy tests.
- `development/test/tests/PriceMonitorAccountTest.php` - account endpoint and assets tests.
- `development/test/tests/PriceMonitorAdminTest.php` - admin capability, nonce, sanitization, redaction tests.
- `tests/price-monitor-account.test.mjs` - frontend account UI tests.

WordPress files to modify:

- `cashback-plugin.php` - load and initialize price monitor classes.
- `includes/class-cashback-rate-limiter.php` - add account price-monitor read/write actions.
- `includes/services/class-cashback-internal-api-service.php` - add WordPress email dispatch method for backend alerts.
- `includes/rest/class-cashback-internal-rest-controller.php` - add internal alert dispatch route.
- `package.json` - add a node test script only if needed by current test invocation.

---

### Task 0: Backend Implementation Branch Preparation

**Files:**
- Modify: none.

**Interfaces:**
- Produces: backend implementation branch `feature/price-monitor-service`.

- [ ] **Step 1: Return to backend develop**

Run in `F:\cash-back\monitor_cashback`:

```powershell
rtk git switch develop
rtk git pull --ff-only
```

Expected: branch is `develop` and up to date with `origin/develop`.

- [ ] **Step 2: Create implementation branch**

Run:

```powershell
rtk git switch -c feature/price-monitor-service
```

Expected: branch `feature/price-monitor-service` is active.

- [ ] **Step 3: Verify no unrelated tracked changes**

Run:

```powershell
rtk git status --short --branch
```

Expected: branch is `feature/price-monitor-service`. A pre-existing untracked `.claude-flow/` directory may appear and must remain untouched.

---

### Task 1: Backend Monitored Sources, Settings, And Admin API

**Files:**
- Create: `src/price_monitor/api/v1/admin.py`
- Create: `src/price_monitor/domains/sources/service.py`
- Create: `src/price_monitor/domains/sources/schemas.py`
- Create: `tests/unit/test_source_service.py`
- Create: `tests/contract/test_admin_api_contract.py`
- Create: `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`
- Modify: `src/price_monitor/main.py`
- Modify: `src/price_monitor/db/models.py`
- Modify: `src/price_monitor/domains/sources/models.py`
- Modify: `src/price_monitor/api/v1/sources.py`

**Interfaces:**
- Produces: `SourceService.upsert_source(payload: MonitoredSourceInput) -> MonitoredSource`
- Produces: `SourceService.find_supported_source(raw_url: str) -> MonitoredSource | None`
- Produces: `GET /api/v1/sources/supported?url=...`
- Produces: `POST /api/v1/admin/sources`
- Produces: `GET /api/v1/admin/sources`
- Produces: `PATCH /api/v1/admin/settings`
- Produces: `GET /api/v1/admin/settings`

- [ ] **Step 1: Write failing source service tests**

Create `tests/unit/test_source_service.py` with:

```python
import pytest
from sqlalchemy.orm import Session

from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService


def test_find_supported_source_matches_domain_and_subdomain(session: Session) -> None:
    service = SourceService(session)
    service.upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert service.find_supported_source("https://example.com/p/1").source_domain == "example.com"
    assert service.find_supported_source("https://shop.example.com/p/1").source_domain == "example.com"


def test_find_supported_source_rejects_paused_source(session: Session) -> None:
    service = SourceService(session)
    service.upsert_source(
        MonitoredSourceInput(
            source_domain="paused.test",
            display_name="Paused",
            logo_url="https://paused.test/logo.png",
            status="paused",
            fetch_interval_hours=12,
            history_retention_days=30,
            browser_fallback_allowed=False,
            proxy_pool_id=None,
        )
    )

    assert service.find_supported_source("https://paused.test/p/1") is None
```

- [ ] **Step 2: Run source service tests and verify RED**

Run:

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
```

Expected: FAIL because `price_monitor.domains.sources.service` or `MonitoredSourceInput` is missing.

- [ ] **Step 3: Add models and source service**

Modify `src/price_monitor/domains/sources/models.py` to keep `SourceStatus` and add:

```python
class MonitoredSource(Base):
    __tablename__ = "monitored_sources"

    source_domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    fetch_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    history_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    browser_fallback_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proxy_pool_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class MonitorSetting(Base):
    __tablename__ = "monitor_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class ProxyPool(Base):
    __tablename__ = "proxy_pools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class ProxyEndpoint(Base):
    __tablename__ = "proxy_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("proxy_pools.id"), nullable=False, index=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    proxy_url_secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
```

Create `src/price_monitor/domains/sources/service.py` with dataclasses:

```python
@dataclass(frozen=True)
class MonitoredSourceInput:
    source_domain: str
    display_name: str
    logo_url: str
    status: str
    fetch_interval_hours: int
    history_retention_days: int
    browser_fallback_allowed: bool
    proxy_pool_id: str | None
```

Implement `SourceService` with normalized domains, status validation, interval minimum `1`, retention range `1..365`, and `find_supported_source()` that calls `validate_public_product_url()` and matches exact domain or subdomain for active sources.

- [ ] **Step 4: Register models and write migration**

Modify `src/price_monitor/db/models.py` to import `MonitoredSource`, `MonitorSetting`, `ProxyPool`, and `ProxyEndpoint`.

Create migration `migrations/versions/20260630_0002_price_monitor_vertical_slice.py` with tables from Step 3 and indexes on `status`, `pool_id`, and `tier`.

- [ ] **Step 5: Run source service tests and verify GREEN**

Run:

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Write failing admin API contract tests**

Create `tests/contract/test_admin_api_contract.py` with signed requests to:

- `POST /api/v1/admin/sources`
- `GET /api/v1/admin/sources`
- `GET /api/v1/sources/supported?url=https://example.com/p/1`
- `PATCH /api/v1/admin/settings`
- `GET /api/v1/admin/settings`

Assert:

```python
assert create.status_code == 201
assert supported.json()["supported"] is True
assert supported.json()["source"]["source_domain"] == "example.com"
assert missing.json() == {
    "supported": False,
    "error": {"code": "unsupported_store", "message": "Магазин не поддерживается"},
}
```

- [ ] **Step 7: Run admin API contract tests and verify RED**

Run:

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
```

Expected: FAIL because admin routes and supported-source endpoint are missing.

- [ ] **Step 8: Implement admin and supported-source endpoints**

Create `src/price_monitor/api/v1/admin.py` with:

- `POST /api/v1/admin/sources` requiring `verify_wordpress_request` and `Idempotency-Key`.
- `GET /api/v1/admin/sources` requiring `verify_wordpress_request`.
- `PATCH /api/v1/admin/settings` requiring `verify_wordpress_request` and idempotency.
- `GET /api/v1/admin/settings` requiring `verify_wordpress_request`.

Modify `src/price_monitor/api/v1/sources.py` with:

- `GET /api/v1/sources/supported?url=...` requiring `verify_wordpress_request`.

Modify `src/price_monitor/main.py`:

```python
from price_monitor.api.v1 import admin, health, internal, price_history, products, sources, watchlist

app.include_router(admin.router)
```

- [ ] **Step 9: Run backend source/admin tests**

Run:

```powershell
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

Run:

```powershell
rtk git add src/price_monitor/api/v1/admin.py src/price_monitor/api/v1/sources.py src/price_monitor/main.py src/price_monitor/db/models.py src/price_monitor/domains/sources tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py migrations/versions/20260630_0002_price_monitor_vertical_slice.py
rtk git commit -m "feat: add monitored source admin api"
```

Expected: commit succeeds.

---

### Task 2: Backend Watchlist Limits, Duplicate Semantics, And Product Card Contract

**Files:**
- Create: `tests/contract/test_product_card_contract.py`
- Modify: `src/price_monitor/domains/watchlist/models.py`
- Modify: `src/price_monitor/domains/watchlist/service.py`
- Modify: `src/price_monitor/domains/products/models.py`
- Modify: `src/price_monitor/api/v1/watchlist.py`
- Modify: `src/price_monitor/api/v1/products.py`
- Modify: `tests/integration/test_watchlist_service.py`
- Modify: `tests/contract/test_api_contract.py`
- Modify: `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`

**Interfaces:**
- Consumes: `SourceService.find_supported_source(raw_url: str) -> MonitoredSource | None`
- Produces: `WatchlistService.add_item(..., max_tracked_products: int = 10) -> WatchlistAddResult`
- Produces: `WatchlistService.update_target_price(item_id: str, user_id: str, target_price_minor: int | None, request_id: str) -> WatchlistItem`
- Produces: `GET /api/v1/products/{product_id}` card response.
- Produces: stable error codes `unsupported_store`, `duplicate_watchlist_item`, `limit_exceeded`, `invalid_target_price`.

- [ ] **Step 1: Write failing watchlist behavior tests**

Extend `tests/integration/test_watchlist_service.py` with:

```python
def test_add_watchlist_item_rejects_unsupported_source(session: Session) -> None:
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://unsupported.test/item",
        target_price_minor=None,
        currency="RUB",
        request_id="req-unsupported",
        max_tracked_products=10,
    )

    assert result.error_code == "unsupported_store"


def test_active_duplicate_returns_error_but_deleted_item_can_be_readded(session: Session) -> None:
    SourceService(session).upsert_source(
        MonitoredSourceInput("example.com", "Example", "https://example.com/logo.png", "active", 6, 90, False, None)
    )
    service = WatchlistService(session)
    first = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42",
        target_price_minor=None,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    duplicate = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42&utm_source=ad",
        target_price_minor=None,
        currency="RUB",
        request_id="req-2",
        max_tracked_products=10,
    )

    assert first.created is True
    assert duplicate.error_code == "duplicate_watchlist_item"

    service.delete_item(item_id=first.item.id, request_id="req-3")
    readded = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42",
        target_price_minor=9000,
        currency="RUB",
        request_id="req-4",
        max_tracked_products=10,
    )

    assert readded.created is True
    assert readded.item.id != first.item.id


def test_max_tracked_products_limit_is_enforced(session: Session) -> None:
    SourceService(session).upsert_source(
        MonitoredSourceInput("example.com", "Example", "https://example.com/logo.png", "active", 6, 90, False, None)
    )
    service = WatchlistService(session)
    first = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/a",
        target_price_minor=None,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=1,
    )
    second = service.add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/b",
        target_price_minor=None,
        currency="RUB",
        request_id="req-2",
        max_tracked_products=1,
    )

    assert first.created is True
    assert second.error_code == "limit_exceeded"
```

- [ ] **Step 2: Run watchlist tests and verify RED**

Run:

```powershell
rtk python -m pytest tests/integration/test_watchlist_service.py -q
```

Expected: FAIL because `max_tracked_products` and `error_code` are not implemented.

- [ ] **Step 3: Implement watchlist service result types**

Modify `src/price_monitor/domains/watchlist/service.py`:

```python
@dataclass(frozen=True)
class WatchlistAddResult:
    item: WatchlistItem | None
    created: bool
    error_code: str | None = None
```

Implement:

- unsupported source check through `SourceService`.
- active duplicate check with `WatchlistItem.status == "active"`.
- active count limit.
- product reuse by source domain and canonical URL hash.
- `active_identity_key = f"{user_id}:{canonical_url_hash}"` on active rows.
- delete sets `status = "deleted"`, `deleted_at`, and `active_identity_key = None`.

- [ ] **Step 4: Modify models and migration for watchlist/product card**

Modify `WatchlistItem`:

```python
active_identity_key: Mapped[str | None] = mapped_column(String(255), unique=True)
updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
```

Drop existing unique constraint `uq_watchlist_user_url_hash` in the migration and add unique constraint/index for `active_identity_key`.

Modify `Product`:

```python
image_url: Mapped[str | None] = mapped_column(String(2048))
rating_value: Mapped[str | None] = mapped_column(String(32))
current_price_minor: Mapped[int | None] = mapped_column(Integer)
currency: Mapped[str | None] = mapped_column(String(3))
last_fetch_status: Mapped[str | None] = mapped_column(String(32))
last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
```

- [ ] **Step 5: Run watchlist tests and verify GREEN**

Run:

```powershell
rtk python -m pytest tests/integration/test_watchlist_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Write failing product card contract tests**

Create `tests/contract/test_product_card_contract.py` with:

```python
def test_product_detail_returns_card_contract(client: TestClient, session: Session) -> None:
    source = SourceService(session).upsert_source(
        MonitoredSourceInput("example.com", "Example", "https://example.com/logo.png", "active", 6, 90, False, None)
    )
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item?id=42",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    product = result.item.product
    product.title = "Example Product"
    product.image_url = "https://example.com/image.jpg"
    product.rating_value = "4.7"
    product.current_price_minor = 12_345
    product.currency = "RUB"
    product.last_fetch_status = "ok"
    session.commit()

    path = f"/api/v1/products/{product.id}"
    response = client.get(path, headers=signed_headers("GET", path, b"", request_id="req-card", idempotency_key=None))

    assert response.status_code == 200
    assert response.json()["product"]["title"] == "Example Product"
    assert response.json()["source"]["logo_url"] == source.logo_url
    assert response.json()["actions"]["direct_url"] == product.canonical_url
```

- [ ] **Step 7: Run product card contract and verify RED**

Run:

```powershell
rtk python -m pytest tests/contract/test_product_card_contract.py -q
```

Expected: FAIL because product detail currently returns `status: not_loaded` and does not require HMAC.

- [ ] **Step 8: Implement product card endpoint and secure reads**

Modify `src/price_monitor/api/v1/products.py`:

- require `verify_wordpress_request`;
- load product and monitored source;
- return:

```json
{
  "product": {
    "id": "...",
    "canonical_url": "...",
    "title": "...",
    "image_url": "...",
    "rating_value": "4.7",
    "current_price_minor": 12345,
    "currency": "RUB",
    "last_fetch_status": "ok"
  },
  "source": {
    "source_domain": "example.com",
    "display_name": "Example",
    "logo_url": "https://example.com/logo.png"
  },
  "actions": {
    "direct_url": "https://example.com/item?id=42"
  }
}
```

Modify watchlist list endpoint to require HMAC and `user_id`.

- [ ] **Step 9: Run Task 2 backend tests**

Run:

```powershell
rtk python -m pytest tests/integration/test_watchlist_service.py tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 2**

Run:

```powershell
rtk git add src/price_monitor/domains/watchlist src/price_monitor/domains/products src/price_monitor/api/v1/watchlist.py src/price_monitor/api/v1/products.py tests/integration/test_watchlist_service.py tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py migrations/versions/20260630_0002_price_monitor_vertical_slice.py
rtk git commit -m "feat: enforce watchlist policy and product card contract"
```

Expected: commit succeeds.

---

### Task 3: Backend Price Chart And Fetch Pipeline With Fake Adapters

**Files:**
- Create: `src/price_monitor/domains/fetching/__init__.py`
- Create: `src/price_monitor/domains/fetching/ports.py`
- Create: `src/price_monitor/domains/fetching/extraction.py`
- Create: `src/price_monitor/domains/fetching/service.py`
- Create: `tests/unit/test_fetch_extraction.py`
- Create: `tests/unit/test_fetch_pipeline.py`
- Modify: `src/price_monitor/domains/reliability/models.py`
- Modify: `src/price_monitor/domains/pricing/models.py`
- Modify: `src/price_monitor/api/v1/price_history.py`
- Modify: `src/price_monitor/workers/tasks/fetch_product.py`
- Modify: `src/price_monitor/db/models.py`
- Modify: `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`

**Interfaces:**
- Produces: `FetchedProductData(title: str, image_url: str | None, price_minor: int, currency: str, rating_value: str | None)`
- Produces: `ProductPageFetcher.fetch(url: str, proxy_url: str | None) -> FetchPageResult`
- Produces: `FetchPipeline.run(product_id: str, now: datetime | None = None) -> ProductFetchResult`
- Produces: `GET /api/v1/products/{product_id}/price-chart`

- [ ] **Step 1: Write failing extraction tests**

Create `tests/unit/test_fetch_extraction.py` with:

```python
from price_monitor.domains.fetching.extraction import extract_product_data


def test_extract_product_data_from_json_ld_product() -> None:
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Phone","image":"https://example.com/p.jpg","aggregateRating":{"ratingValue":"4.8"},"offers":{"price":"123.45","priceCurrency":"RUB"}}
    </script>
    </head><body></body></html>
    """

    data = extract_product_data(html, fallback_currency="RUB")

    assert data.title == "Phone"
    assert data.image_url == "https://example.com/p.jpg"
    assert data.price_minor == 12345
    assert data.currency == "RUB"
    assert data.rating_value == "4.8"


def test_extract_product_data_returns_none_when_price_or_title_missing() -> None:
    assert extract_product_data("<html><title>No price</title></html>", fallback_currency="RUB") is None
```

- [ ] **Step 2: Run extraction tests and verify RED**

Run:

```powershell
rtk python -m pytest tests/unit/test_fetch_extraction.py -q
```

Expected: FAIL because fetching domain is missing.

- [ ] **Step 3: Implement extraction and ports**

Create `ports.py`:

```python
@dataclass(frozen=True)
class FetchedProductData:
    title: str
    image_url: str | None
    price_minor: int
    currency: str
    rating_value: str | None


@dataclass(frozen=True)
class FetchPageResult:
    content: str
    final_url: str
    http_status: int
    response_ms: int


class ProductPageFetcher(Protocol):
    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        """Fetch a public product page."""
```

Create `extraction.py` with standard-library JSON-LD parsing using `html.parser`, handling `Product`, `@graph`, list roots, `offers.price`, `offers.lowPrice`, `image` as string/list/object, and decimal-to-minor conversion with `Decimal`.

- [ ] **Step 4: Run extraction tests and verify GREEN**

Run:

```powershell
rtk python -m pytest tests/unit/test_fetch_extraction.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing fetch pipeline tests**

Create `tests/unit/test_fetch_pipeline.py` with fake fetchers:

```python
class FakeFetcher:
    def __init__(self, html: str) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.html = html

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        self.calls.append((url, proxy_url))
        return FetchPageResult(content=self.html, final_url=url, http_status=200, response_ms=7)
```

Assert:

- direct fetch succeeds before proxy/browser;
- product card fields update;
- price point is inserted;
- failed direct fetch falls back to proxy tier;
- browser fallback is skipped when source flag is false;
- fetch attempt rows store redacted proxy tier and error class.

- [ ] **Step 6: Run fetch pipeline tests and verify RED**

Run:

```powershell
rtk python -m pytest tests/unit/test_fetch_pipeline.py -q
```

Expected: FAIL because `FetchPipeline` and `FetchAttempt` do not exist.

- [ ] **Step 7: Add fetch attempt model and pipeline**

Modify `src/price_monitor/domains/reliability/models.py`:

```python
class FetchAttempt(Base):
    __tablename__ = "fetch_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    fetch_job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    proxy_tier: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_ms: Mapped[int | None] = mapped_column(Integer)
    product_data_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
```

Modify `PricePoint` with `fetch_attempt_id: Mapped[str | None]`.

Create `service.py` with `FetchPipeline` that accepts injected direct/proxy/browser fake fetchers in tests and updates product + price point in one transaction.

- [ ] **Step 8: Implement price chart endpoint**

Modify `src/price_monitor/api/v1/price_history.py`:

- require HMAC on `price-history`;
- add `GET /api/v1/products/{product_id}/price-chart`;
- return daily points for `days=1..90`:

```json
{
  "product_id": "...",
  "currency": "RUB",
  "points": [{"date": "2026-06-30", "min_price_minor": 12345, "max_price_minor": 12345}],
  "summary": {"lowest_price_minor": 12345, "latest_price_minor": 12345}
}
```

- [ ] **Step 9: Wire Celery task**

Modify `src/price_monitor/workers/tasks/fetch_product.py` so `fetch_product(product_id)` opens a DB session and calls `FetchPipeline.run(product_id=product_id)`. Return `{"product_id": product_id, "status": result.status}`.

- [ ] **Step 10: Run Task 3 tests**

Run:

```powershell
rtk python -m pytest tests/unit/test_fetch_extraction.py tests/unit/test_fetch_pipeline.py tests/contract/test_product_card_contract.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit Task 3**

Run:

```powershell
rtk git add src/price_monitor/domains/fetching src/price_monitor/domains/reliability/models.py src/price_monitor/domains/pricing/models.py src/price_monitor/api/v1/price_history.py src/price_monitor/workers/tasks/fetch_product.py src/price_monitor/db/models.py tests/unit/test_fetch_extraction.py tests/unit/test_fetch_pipeline.py migrations/versions/20260630_0002_price_monitor_vertical_slice.py
rtk git commit -m "feat: add product fetch pipeline and chart api"
```

Expected: commit succeeds.

---

### Task 4: Backend Desired-Price Alerts And WordPress Dispatch Contract

**Files:**
- Create: `src/price_monitor/domains/notifications/service.py`
- Create: `tests/unit/test_notification_service.py`
- Modify: `src/price_monitor/domains/reliability/models.py`
- Modify: `src/price_monitor/db/models.py`
- Modify: `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`

**Interfaces:**
- Consumes: `WatchlistItem.target_price_minor`
- Consumes: `Product.current_price_minor`
- Produces: `NotificationService.evaluate_product(product_id: str, now: datetime) -> list[AlertEvent]`
- Produces: outbox event type `notification.price_target_reached`

- [ ] **Step 1: Write failing notification tests**

Create `tests/unit/test_notification_service.py`:

```python
def test_price_target_alert_created_once_per_threshold_crossing(session: Session) -> None:
    source = SourceService(session).upsert_source(
        MonitoredSourceInput("example.com", "Example", "https://example.com/logo.png", "active", 6, 90, False, None)
    )
    result = WatchlistService(session).add_item(
        user_id="wp:savello.test:1",
        product_url="https://example.com/item",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-1",
        max_tracked_products=10,
    )
    product = result.item.product
    product.current_price_minor = 9_999
    product.currency = "RUB"
    session.flush()

    first = NotificationService(session).evaluate_product(product_id=product.id, now=datetime(2026, 6, 30, tzinfo=UTC))
    second = NotificationService(session).evaluate_product(product_id=product.id, now=datetime(2026, 6, 30, 1, tzinfo=UTC))

    assert len(first) == 1
    assert second == []
```

- [ ] **Step 2: Run notification tests and verify RED**

Run:

```powershell
rtk python -m pytest tests/unit/test_notification_service.py -q
```

Expected: FAIL because `NotificationService` and `AlertEvent` are missing.

- [ ] **Step 3: Add alert model and service**

Modify `src/price_monitor/domains/reliability/models.py`:

```python
class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_alert_events_dedup_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    watchlist_item_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Implement `NotificationService.evaluate_product()`:

- only active watchlist items;
- target price is not null;
- product current price is not null;
- product price is `<= target_price_minor`;
- dedup key is `price-target:{watchlist_item_id}:{target_price_minor}:{observed_price_minor}`;
- creates `AlertEvent` and `OutboxEvent` once.

- [ ] **Step 4: Run notification tests and verify GREEN**

Run:

```powershell
rtk python -m pytest tests/unit/test_notification_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Wire alert evaluation into fetch pipeline**

Modify `FetchPipeline.run()` to call `NotificationService.evaluate_product()` after product/price point update. Add an assertion to `tests/unit/test_fetch_pipeline.py` that a price crossing creates one pending alert event.

- [ ] **Step 6: Run fetch and notification tests**

Run:

```powershell
rtk python -m pytest tests/unit/test_fetch_pipeline.py tests/unit/test_notification_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

Run:

```powershell
rtk git add src/price_monitor/domains/notifications/service.py src/price_monitor/domains/reliability/models.py src/price_monitor/domains/fetching/service.py src/price_monitor/db/models.py tests/unit/test_notification_service.py tests/unit/test_fetch_pipeline.py migrations/versions/20260630_0002_price_monitor_vertical_slice.py
rtk git commit -m "feat: add desired price alert events"
```

Expected: commit succeeds.

---

### Task 5: Backend Full Gates And Migration Smoke

**Files:**
- Modify only files from Tasks 1-4 if gates expose defects.

**Interfaces:**
- Consumes all backend interfaces from Tasks 1-4.
- Produces a backend branch ready for WordPress integration.

- [ ] **Step 1: Run backend targeted suites**

Run:

```powershell
rtk python -m pytest tests/unit/test_source_service.py tests/unit/test_fetch_extraction.py tests/unit/test_fetch_pipeline.py tests/unit/test_notification_service.py tests/integration/test_watchlist_service.py tests/contract/test_admin_api_contract.py tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend quality gates**

Run:

```powershell
rtk python -m pytest
rtk python -m ruff check .
rtk python -m ruff format --check .
rtk python -m mypy
rtk docker compose config --quiet
rtk git diff --check
```

Expected: all commands pass. The existing Starlette deprecation warning in pytest may remain if no behavior changed around TestClient.

- [ ] **Step 3: Run migration smoke with SQLite if local PostgreSQL is unavailable**

Run:

```powershell
$env:PRICE_MONITOR_DATABASE_URL='sqlite:///migration-smoke.db'; rtk alembic upgrade head
```

Expected: migration reaches `head`. Remove `migration-smoke.db` after smoke with PowerShell `Remove-Item -LiteralPath migration-smoke.db` only after confirming the path is exactly in the repo root.

- [ ] **Step 4: Commit gate fixes if any were needed**

If Step 2 or Step 3 required fixes, run:

```powershell
rtk git add src/price_monitor tests migrations
rtk git commit -m "fix: pass price monitor backend gates"
```

Expected: commit exists only when files changed.

---

### Task 6: WordPress Backend Client And Account REST Proxy

**Files:**
- Create: `includes/price-monitor/class-cashback-price-monitor-client.php`
- Create: `includes/price-monitor/class-cashback-price-monitor-rest-controller.php`
- Create: `development/test/tests/PriceMonitorClientTest.php`
- Create: `development/test/tests/PriceMonitorRestControllerTest.php`
- Modify: `cashback-plugin.php`
- Modify: `includes/class-cashback-rate-limiter.php`

**Interfaces:**
- Consumes backend HMAC canonical message: `METHOD\nPATH\nTIMESTAMP\nREQUEST_ID\nBODY_SHA256`
- Produces: `Cashback_Price_Monitor_Client::request(string $method, string $path, array $payload = array(), ?string $idempotency_key = null): array|WP_Error`
- Produces: `cashback/v1/price-monitor/items` account REST endpoints.
- Consumes existing `Cashback_Link_Checker_Service`.

- [ ] **Step 1: Switch to a WordPress implementation branch**

Run in `F:\wamp64\www\kash-back\wp-content\plugins\cash-back`:

```powershell
rtk git switch main
rtk git pull --ff-only
rtk git switch -c feature/price-monitor-wordpress-ui
```

Expected: branch `feature/price-monitor-wordpress-ui` exists and status is clean before edits.

- [ ] **Step 2: Write failing client signing tests**

Create `development/test/tests/PriceMonitorClientTest.php` with assertions:

- signed headers include `X-Request-Id`, `X-Request-Timestamp`, `X-Body-SHA256`, `X-Signature`;
- body hash is SHA-256 of exact JSON body;
- signature equals HMAC-SHA256 over backend canonical message;
- secret value is never returned by `redacted_settings()`.

- [ ] **Step 3: Run client test and verify RED**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorClientTest
```

Expected: FAIL because client class is missing.

- [ ] **Step 4: Implement backend client**

Create `class-cashback-price-monitor-client.php`:

- options:
  - `cashback_price_monitor_backend_url`;
  - `cashback_price_monitor_backend_secret`;
  - `cashback_price_monitor_enabled`;
- `request()` builds JSON with `wp_json_encode($payload, JSON_UNESCAPED_SLASHES)`;
- signs method/path/timestamp/request id/body hash;
- sends through `wp_remote_request`;
- returns decoded array or `WP_Error`;
- redacts all secrets in diagnostics.

- [ ] **Step 5: Run client test and verify GREEN**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorClientTest
```

Expected: PASS.

- [ ] **Step 6: Write failing account REST proxy tests**

Create `development/test/tests/PriceMonitorRestControllerTest.php` asserting:

- route registration under `cashback/v1/price-monitor`;
- missing REST nonce returns 403;
- unauthenticated add returns 401 or 403 according to current plugin test helpers;
- authenticated add calls backend `GET /api/v1/sources/supported`;
- unsupported source returns `unsupported_store`;
- supported source calls backend `POST /api/v1/watchlist/items`;
- activation metadata is obtained through `Cashback_Link_Checker_Service`.

- [ ] **Step 7: Run REST proxy tests and verify RED**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorRestControllerTest
```

Expected: FAIL because routes are missing.

- [ ] **Step 8: Implement REST proxy controller**

Create `class-cashback-price-monitor-rest-controller.php` with:

- `POST /items`;
- `GET /items`;
- `PATCH /items/(?P<item_id>[A-Za-z0-9_-]+)`;
- `DELETE /items/(?P<item_id>[A-Za-z0-9_-]+)`;
- `POST /items/(?P<item_id>[A-Za-z0-9_-]+)/refresh`;
- REST nonce verification matching link-checker controller style;
- rate-limit actions `cashback_price_monitor_read` and `cashback_price_monitor_write`;
- `external_user_id = 'wp:' . wp_parse_url(home_url('/'), PHP_URL_HOST) . ':' . get_current_user_id()`;
- backend idempotency keys from client request id or UUID.

Modify `cashback-plugin.php` to require and initialize the class.

Modify `includes/class-cashback-rate-limiter.php` to add read/write action keys.

- [ ] **Step 9: Run WordPress REST proxy tests**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter "PriceMonitorClientTest|PriceMonitorRestControllerTest"
```

Expected: PASS.

- [ ] **Step 10: Commit Task 6**

Run in the WordPress plugin repo:

```powershell
rtk git add includes/price-monitor/class-cashback-price-monitor-client.php includes/price-monitor/class-cashback-price-monitor-rest-controller.php cashback-plugin.php includes/class-cashback-rate-limiter.php development/test/tests/PriceMonitorClientTest.php development/test/tests/PriceMonitorRestControllerTest.php
rtk git commit -m "feat: add price monitor backend proxy"
```

Expected: commit succeeds.

---

### Task 7: WordPress Admin Settings And Account UI

**Files:**
- Create: `includes/price-monitor/class-cashback-price-monitor-account.php`
- Create: `admin/class-cashback-price-monitor-admin.php`
- Create: `assets/js/price-monitor-account.js`
- Create: `assets/css/price-monitor-account.css`
- Create: `assets/js/price-monitor-admin.js`
- Create: `assets/css/price-monitor-admin.css`
- Create: `development/test/tests/PriceMonitorAccountTest.php`
- Create: `development/test/tests/PriceMonitorAdminTest.php`
- Create: `tests/price-monitor-account.test.mjs`
- Modify: `cashback-plugin.php`

**Interfaces:**
- Consumes: `Cashback_Price_Monitor_Client`
- Consumes: `cashback/v1/price-monitor` REST endpoints.
- Produces: WooCommerce account endpoint `price-monitor`.
- Produces: admin page under existing cashback admin parent.

- [ ] **Step 1: Write failing account PHP tests**

Create `development/test/tests/PriceMonitorAccountTest.php` asserting:

- account endpoint is registered;
- menu item text is `Мониторинг цен`;
- assets enqueue only on the endpoint;
- localized config contains REST base, nonce, and Russian UI strings.

- [ ] **Step 2: Run account PHP tests and verify RED**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorAccountTest
```

Expected: FAIL because account class is missing.

- [ ] **Step 3: Implement account endpoint class**

Create `class-cashback-price-monitor-account.php`:

- add WooCommerce account endpoint `price-monitor`;
- add account menu item `Мониторинг цен`;
- render form with URL input, desired price input, add button, and card container;
- enqueue `cashback-account-base`, `price-monitor-account.css`, and `price-monitor-account.js`;
- localize REST base `rest_url('cashback/v1/price-monitor')`, nonce, logged-in flag, and UI messages.

- [ ] **Step 4: Run account PHP tests and verify GREEN**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorAccountTest
```

Expected: PASS.

- [ ] **Step 5: Write failing admin tests**

Create `development/test/tests/PriceMonitorAdminTest.php` asserting:

- admin submenu is registered under `cashback-overview`;
- saving settings requires `manage_options`;
- nonce failure rejects save;
- backend URL is sanitized with `esc_url_raw`;
- secrets are saved but rendered as redacted;
- source domain, logo URL, interval, retention, and browser flag are sanitized before client call.

- [ ] **Step 6: Run admin tests and verify RED**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorAdminTest
```

Expected: FAIL because admin class is missing.

- [ ] **Step 7: Implement admin class and assets**

Create `admin/class-cashback-price-monitor-admin.php`:

- submenu title `Мониторинг цен`;
- settings form for backend URL, enabled flag, backend secret, user limit;
- source form for domain, name, logo URL, interval hours, retention days, browser fallback;
- proxy pool form with tier and secret reference fields;
- diagnostic table using redacted values from backend admin endpoints;
- all save actions use capability checks and `check_admin_referer`.

Create admin CSS/JS for form state, not business logic.

- [ ] **Step 8: Run admin tests and verify GREEN**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorAdminTest
```

Expected: PASS.

- [ ] **Step 9: Write failing account JS tests**

Create `tests/price-monitor-account.test.mjs` asserting:

- unsupported store renders `Магазин не поддерживается`;
- duplicate renders `Товар уже отслеживается`;
- limit renders `Достигнут лимит отслеживаемых товаров`;
- successful add renders image, title, price, rating, source logo, chart canvas or SVG, and action button;
- menu edit updates desired price through PATCH;
- menu delete removes card through DELETE;
- cashback action opens activation URL from REST response.

- [ ] **Step 10: Run JS test and verify RED**

Run:

```powershell
rtk node --test tests/price-monitor-account.test.mjs
```

Expected: FAIL because account JS is missing.

- [ ] **Step 11: Implement account JS and CSS**

Create `assets/js/price-monitor-account.js`:

- delegated submit for add form;
- `fetch()` wrapper with `X-WP-Nonce`;
- render loading, error, empty, and card states;
- render card menu with edit desired price and delete;
- keep activation button behavior aligned with existing link-checker pattern.

Create `assets/css/price-monitor-account.css`:

- compact account panel layout;
- card grid;
- product image aspect ratio;
- price chart area with stable dimensions;
- menu button and red delete action.

- [ ] **Step 12: Run account UI tests**

Run:

```powershell
rtk node --test tests/price-monitor-account.test.mjs
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter "PriceMonitorAccountTest|PriceMonitorAdminTest|PriceMonitorRestControllerTest"
```

Expected: PASS.

- [ ] **Step 13: Commit Task 7**

Run in the WordPress plugin repo:

```powershell
rtk git add includes/price-monitor/class-cashback-price-monitor-account.php admin/class-cashback-price-monitor-admin.php assets/js/price-monitor-account.js assets/css/price-monitor-account.css assets/js/price-monitor-admin.js assets/css/price-monitor-admin.css cashback-plugin.php development/test/tests/PriceMonitorAccountTest.php development/test/tests/PriceMonitorAdminTest.php tests/price-monitor-account.test.mjs
rtk git commit -m "feat: add price monitor admin and account ui"
```

Expected: commit succeeds.

---

### Task 8: WordPress Internal Email Dispatch For Alerts

**Files:**
- Modify: `includes/services/class-cashback-internal-api-service.php`
- Modify: `includes/rest/class-cashback-internal-rest-controller.php`
- Create: `development/test/tests/PriceMonitorAlertDispatchTest.php`

**Interfaces:**
- Consumes backend outbox payload `notification.price_target_reached`.
- Produces: `POST /savello-internal/v1/price-monitor/alerts/send`
- Produces: `Savello_Cashback_Internal_API_Service::send_price_monitor_alert(array $payload): array|WP_Error`

- [ ] **Step 1: Write failing alert dispatch tests**

Create `PriceMonitorAlertDispatchTest.php` asserting:

- internal route is registered;
- route requires existing internal HMAC;
- invalid user id returns 404;
- valid payload calls `wp_mail` test double with product title, observed price, target price, product URL, and action URL;
- response returns `{"status":"sent"}`.

- [ ] **Step 2: Run alert dispatch test and verify RED**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorAlertDispatchTest
```

Expected: FAIL because route and service method are missing.

- [ ] **Step 3: Implement internal alert route**

Modify `class-cashback-internal-rest-controller.php`:

```php
register_rest_route(self::NAMESPACE, '/price-monitor/alerts/send', array(
    'methods'             => WP_REST_Server::CREATABLE,
    'callback'            => array( $this, 'send_price_monitor_alert' ),
    'permission_callback' => array( $this, 'check_hmac' ),
));
```

Add callback that passes JSON params to `send_price_monitor_alert()`.

Modify internal API service to sanitize payload, load user email, build a short Russian email, and call `wp_mail()`.

- [ ] **Step 4: Run alert dispatch tests and verify GREEN**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter PriceMonitorAlertDispatchTest
```

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

Run:

```powershell
rtk git add includes/services/class-cashback-internal-api-service.php includes/rest/class-cashback-internal-rest-controller.php development/test/tests/PriceMonitorAlertDispatchTest.php
rtk git commit -m "feat: add price monitor alert email dispatch"
```

Expected: commit succeeds.

---

### Task 9: WordPress Full Gates

**Files:**
- Modify only files from Tasks 6-8 if gates expose defects.

**Interfaces:**
- Consumes all WordPress interfaces from Tasks 6-8.
- Produces WordPress feature branch ready for backend integration smoke.

- [ ] **Step 1: Run targeted WordPress tests**

Run:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter "PriceMonitor|InternalHmacAuthServiceTest|InternalRestControllerStructuralTest|InternalApiServiceTest|LinkCheckerRegistrationTest"
rtk node --test tests/price-monitor-account.test.mjs
rtk node --test tests/cashback-link-checker.test.mjs
```

Expected: PASS.

- [ ] **Step 2: Run syntax checks for changed PHP files**

Run one command per changed PHP file:

```powershell
rtk php -l includes/price-monitor/class-cashback-price-monitor-client.php
rtk php -l includes/price-monitor/class-cashback-price-monitor-rest-controller.php
rtk php -l includes/price-monitor/class-cashback-price-monitor-account.php
rtk php -l admin/class-cashback-price-monitor-admin.php
rtk php -l includes/services/class-cashback-internal-api-service.php
rtk php -l includes/rest/class-cashback-internal-rest-controller.php
```

Expected: each reports no syntax errors.

- [ ] **Step 3: Run lint and whitespace gates**

Run:

```powershell
rtk vendor\bin\phpcs.bat --standard=phpcs.xml --filter=GitModified
rtk git diff --check
```

Expected: PASS. If PHPCS reports unrelated baseline files, rerun with changed-file paths and record the unrelated baseline separately.

- [ ] **Step 4: Commit gate fixes if needed**

If gates required fixes, run:

```powershell
rtk git add includes/price-monitor admin/class-cashback-price-monitor-admin.php assets/js/price-monitor-account.js assets/css/price-monitor-account.css assets/js/price-monitor-admin.js assets/css/price-monitor-admin.css includes/services/class-cashback-internal-api-service.php includes/rest/class-cashback-internal-rest-controller.php cashback-plugin.php development/test/tests tests/price-monitor-account.test.mjs
rtk git commit -m "fix: pass price monitor wordpress gates"
```

Expected: commit exists only when files changed.

---

### Task 10: End-To-End Local And Test Server Verification

**Files:**
- Create: `docs/price-monitor-test-smoke.md`
- Modify deployment docs only if a real command changes.

**Interfaces:**
- Consumes backend and WordPress branches from earlier tasks.
- Produces server evidence for the final release report.

- [ ] **Step 1: Backend final gates**

Run in backend repo:

```powershell
rtk python -m pytest
rtk python -m ruff check .
rtk python -m ruff format --check .
rtk python -m mypy
rtk docker compose config --quiet
rtk git diff --check
```

Expected: PASS.

- [ ] **Step 2: WordPress final gates**

Run in plugin repo:

```powershell
rtk development\test\vendor\bin\phpunit.bat --configuration development\test\phpunit.xml.dist --filter "PriceMonitor|InternalHmacAuthServiceTest|InternalRestControllerStructuralTest|InternalApiServiceTest|LinkCheckerRegistrationTest"
rtk node --test tests/price-monitor-account.test.mjs
rtk vendor\bin\phpcs.bat --standard=phpcs.xml --filter=GitModified
rtk git diff --check
```

Expected: PASS or documented unrelated baseline separated by exact test/sniff name.

- [ ] **Step 3: Push branches**

Run:

```powershell
rtk git push -u origin feature/price-monitor-service
```

Run in plugin repo:

```powershell
rtk git push -u origin feature/price-monitor-wordpress-ui
```

Expected: both pushes succeed.

- [ ] **Step 4: Trigger backend test deploy according to repo policy**

Follow `docs/deploy.md`: backend test deploy runs from `develop`. Merge through the repo-approved path after branch gates pass, then push `develop`.

Expected: GitHub Actions `quality`, `secret-scan`, and `deploy-test` jobs pass.

- [ ] **Step 5: Server smoke**

On the test server or through CI logs, prove:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Expected: both return healthy JSON.

Then run signed smoke calls through WordPress or a checked-in smoke helper:

1. add supported source `example.com`;
2. unsupported source returns `unsupported_store`;
3. supported URL creates watchlist item;
4. same URL returns `duplicate_watchlist_item`;
5. limit returns `limit_exceeded`;
6. fetch updates product card fields;
7. price chart returns at least one point;
8. target price creates alert event and WordPress dispatch returns `sent`;
9. delete marks watch inactive and product/history remain.

- [ ] **Step 6: Record smoke evidence**

Create `docs/price-monitor-test-smoke.md` with:

- commit hashes for backend and WordPress;
- CI run URL or run id;
- server health output;
- smoke request ids;
- result summary for each requirement above;
- any unrelated baseline failures with exact names.

- [ ] **Step 7: Commit smoke evidence**

Run in the backend repo:

```powershell
rtk git add docs/price-monitor-test-smoke.md
rtk git commit -m "docs: record price monitor smoke verification"
```

Expected: commit succeeds.

---

## Final Release Report Requirements

The final response after implementation must include:

- backend branch and commit hashes;
- WordPress branch and commit hashes;
- files changed;
- tests added;
- commands run and results;
- server deployment evidence;
- explicit non-goals not implemented;
- any unrelated baseline failures separated from feature validation.

Do not mark the goal complete until all explicit requirements in the approved
design and this plan have current evidence.
