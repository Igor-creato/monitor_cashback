# Price Compare Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a legal feed-first product price comparison search service and integrate it with the existing cashback WordPress plugin without duplicating cashback lookup or partner-link generation.

**Architecture:** The microservice owns normalized offer storage, import status, search, sorting, and signed `POST /api/v1/search`. WordPress owns user/admin UI, browser-safe REST proxying, cashback enrichment through the existing direct-link module, and safe rendering. CPA integrations are treated as store/campaign/deeplink sources unless a real product-feed/API source is configured.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Celery/RabbitMQ/Redis in `F:\cash-back\monitor_cashback`; PHP/WordPress/WooCommerce/PHPUnit/Node test runner in `F:\wamp64\www\kash-back\wp-content\plugins\cash-back`.

## Global Constraints

- Branches: service `feature/price-compare-search-service`; WordPress `feature/price-compare-search-wordpress`.
- Every shell command must be prefixed with `rtk`.
- No business code before a failing test has been written and observed failing for the expected reason.
- Do not add aggressive scraping, CAPTCHA bypass, hidden browser automation, credential stuffing, or anti-bot evasion.
- Browser JavaScript must call only WordPress REST, never the microservice directly with a secret.
- Reuse existing cashback lookup and partner-link generation: `Cashback_Link_Checker_Service` and `Savello_Cashback_Internal_API_Service::resolve_direct_product_link()`.
- User-visible copy for this feature is Russian: `Сравнить цену`, `Город`, `Название товара`, `Поиск`, `Товаров не нашлось`, `Ошибка поиска`, `Активировать кэшбэк`, `Купить`, `Кэшбэк не определён`.
- If a store has no legal full-catalog product source, return a clear `FEED_NOT_COVERING_FULL_CATALOG` warning/status instead of invented data.
- Secrets must come from env/options and must not be shown in browser payloads, logs, REST errors, docs, or test fixtures.

## Current Code Map

- Service shell: `F:\cash-back\monitor_cashback\src\price_monitor\main.py` owns app creation and health endpoints.
- Service HMAC helper: `src\price_monitor\core\security.py` signs method, path/query, timestamp, request id, and body hash.
- Service DB/Celery infra: `src\price_monitor\db\session.py`, `src\price_monitor\db\base.py`, `src\price_monitor\workers\celery_app.py`.
- Service migrations: current head `migrations\versions\20260703_0005_drop_price_monitor_domain.py` removed the old domain tables.
- Plugin bootstrap: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\cashback-plugin.php`.
- Plugin account pattern: `cashback-withdrawal.php`, `cashback-history.php`, `support\user-support.php`.
- Plugin admin submenu pattern: `admin\class-cashback-shop-import-admin.php`, `admin\class-cashback-settings-admin.php`.
- Plugin browser-safe REST pattern: `includes\link-checker\class-cashback-link-checker-rest-controller.php`.
- Plugin cashback/deeplink seam: `includes\services\class-cashback-internal-api-service.php`.
- Plugin HMAC/internal API seam: `includes\services\class-internal-hmac-auth-service.php`, `includes\rest\class-cashback-internal-rest-controller.php`.

## Data Source Feasibility

- Existing Admitad/Advcake plugin adapters import connected campaigns/offers, rates, store URLs, and deeplink data; they do not expose full SKU-level product catalogs in this checkout.
- `supports_product_feed => false` in the internal merchant payload is a current-code blocker for assuming product feeds from the CPA layer.
- Yandex Market, Wildberries, Ozon, and Joom official docs expose seller/merchant APIs that can manage or read the authenticated seller's own catalog, prices, stock, or products. These are legal sources only when credentials/authorization for that seller account are provided.
- Citilink has no verified public full-catalog product feed/API in the current local code or official public evidence gathered for this plan.
- MVP implementation therefore needs a generic legal feed/API ingestion interface plus a fixture/custom feed path for verification; store-specific production connectors stay `disabled`/`custom` until real access is configured.

## File Structure

### Service Repo

- Create `src/price_monitor/price_compare/schemas.py`: Pydantic request/response DTOs and stable error codes.
- Create `src/price_monitor/price_compare/models.py`: SQLAlchemy `StoreSource`, `Offer`, `ImportStatus`.
- Create `src/price_monitor/price_compare/repository.py`: offer/store query and upsert operations.
- Create `src/price_monitor/price_compare/search.py`: normalization, filtering, pagination, and price sorting.
- Create `src/price_monitor/price_compare/feed.py`: fixture/custom feed normalization and import result accounting.
- Create `src/price_monitor/price_compare/auth.py`: FastAPI dependency around existing HMAC verification.
- Create `src/price_monitor/api/v1/search.py`: `POST /api/v1/search`.
- Modify `src/price_monitor/main.py`: include the search router.
- Modify `src/price_monitor/db/base.py`: import price comparison models for Alembic metadata.
- Add Alembic migration after `20260703_0005`: create store/source/offer/import status tables.
- Add tests under `tests/unit/test_price_compare_*.py`.

### WordPress Plugin Repo

- Create `includes/price-comparison/class-cashback-price-comparison-service.php`: validates input, calls microservice client, enriches rows with cashback, caches checks.
- Create `includes/price-comparison/class-cashback-price-comparison-client.php`: server-to-server signed request to microservice.
- Create `includes/price-comparison/class-cashback-price-comparison-rest-controller.php`: `cashback/v1/price-comparison/search`.
- Create `includes/price-comparison/class-cashback-price-comparison-account.php`: Woo account endpoint/menu/page.
- Create `admin/class-cashback-price-comparison-admin.php`: admin settings/status page under `cashback-overview`.
- Create `assets/js/cashback-price-comparison.js`: form validation, REST request, safe card rendering.
- Create `assets/css/cashback-price-comparison.css`: compact result cards aligned with existing account/admin styling.
- Modify `cashback-plugin.php`: require/init the new classes and activation rewrite endpoint.
- Add PHPUnit tests under `development/test/tests/PriceComparison*.php`.
- Add Node test `tests/price-comparison-form.test.mjs`.

---

### Task 1: Backend Search Contract And Validation

**Files:**
- Create: `tests/unit/test_price_compare_search_contract.py`
- Create: `src/price_monitor/price_compare/schemas.py`
- Create: `src/price_monitor/api/v1/search.py`
- Modify: `src/price_monitor/main.py`

**Interfaces:**
- Produces: `SearchRequest`, `SearchResponse`, `SearchErrorCode`, `router`.
- Consumes: existing `create_app()`.

- [ ] **Step 1: Write the failing API contract test**

```python
from fastapi.testclient import TestClient

from price_monitor.main import create_app


def test_search_rejects_empty_city_with_safe_error() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone 15 128", "city": "", "limit": 50, "offset": 0},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_CITY"
    assert "traceback" not in response.text.lower()
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk python -m pytest tests\unit\test_price_compare_search_contract.py -q`

Expected: failure with `404 Not Found` because `/api/v1/search` is not mounted.

- [ ] **Step 3: Add minimal schemas and route**

Implement `SearchRequest` with non-empty `query`, non-empty `city`, `limit <= 50`, `offset >= 0`. Implement `POST /api/v1/search` returning `400 INVALID_CITY` or `400 INVALID_QUERY` before any search logic.

- [ ] **Step 4: Run test to verify GREEN**

Run: `rtk python -m pytest tests\unit\test_price_compare_search_contract.py -q`

Expected: `1 passed`.

### Task 2: Backend Normalized Offer Search

**Files:**
- Create: `tests/unit/test_price_compare_search_sorting.py`
- Create: `src/price_monitor/price_compare/search.py`
- Extend: `src/price_monitor/price_compare/schemas.py`

**Interfaces:**
- Consumes: `SearchRequest`.
- Produces: `normalize_query(text: str) -> str`, `sort_offers_by_price(offers: list[OfferSearchRow]) -> list[OfferSearchRow]`.

- [ ] **Step 1: Write failing sorting test**

```python
from decimal import Decimal

from price_monitor.price_compare.search import OfferSearchRow, sort_offers_by_price


def test_sort_offers_by_price_keeps_unknown_availability_after_known_items() -> None:
    offers = [
        OfferSearchRow(id="b", title="B", price=Decimal("120.00"), availability="unknown"),
        OfferSearchRow(id="a", title="A", price=Decimal("100.00"), availability="in_stock"),
        OfferSearchRow(id="c", title="C", price=Decimal("90.00"), availability="out_of_stock"),
    ]

    sorted_ids = [offer.id for offer in sort_offers_by_price(offers)]

    assert sorted_ids == ["a", "b", "c"]
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk python -m pytest tests\unit\test_price_compare_search_sorting.py -q`

Expected: `ModuleNotFoundError` or import error for missing `price_compare.search`.

- [ ] **Step 3: Implement minimal value object and sorter**

Implement `OfferSearchRow` as a frozen dataclass and sort by availability rank then numeric price: `in_stock`, `unknown`, `out_of_stock`.

- [ ] **Step 4: Run test to verify GREEN**

Run: `rtk python -m pytest tests\unit\test_price_compare_search_sorting.py -q`

Expected: `1 passed`.

### Task 3: Backend Store/Offer Storage And Feed Import

**Files:**
- Create: `tests/unit/test_price_compare_feed_import.py`
- Create: `src/price_monitor/price_compare/models.py`
- Create: `src/price_monitor/price_compare/feed.py`
- Create: `src/price_monitor/price_compare/repository.py`
- Modify: `src/price_monitor/db/base.py`
- Add migration: `migrations/versions/20260703_0006_add_price_compare_tables.py`

**Interfaces:**
- Produces: `normalize_feed_item(raw: Mapping[str, object], source: str, store_domain: str) -> NormalizedOffer`.
- Produces tables: `price_compare_store_sources`, `price_compare_offers`, `price_compare_import_statuses`.

- [ ] **Step 1: Write failing feed normalization test**

```python
from decimal import Decimal

from price_monitor.price_compare.feed import normalize_feed_item


def test_normalize_feed_item_maps_required_offer_fields() -> None:
    offer = normalize_feed_item(
        {
            "external_id": "sku-1",
            "title": " iPhone 15 128 ",
            "price": "79990.50",
            "currency": "rub",
            "url": "https://example-shop.ru/product/sku-1",
            "availability": "available",
        },
        source="custom",
        store_domain="example-shop.ru",
    )

    assert offer.title == "iPhone 15 128"
    assert offer.price == Decimal("79990.50")
    assert offer.currency == "RUB"
    assert offer.availability == "in_stock"
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk python -m pytest tests\unit\test_price_compare_feed_import.py -q`

Expected: missing module/function failure.

- [ ] **Step 3: Implement minimal normalizer and ORM models**

Implement custom/fixture feed normalization only. Mark `admitad` and `advcake` product-feed ingestion as `FEED_NOT_COVERING_FULL_CATALOG` unless a configured product feed URL is present.

- [ ] **Step 4: Run migration metadata and tests**

Run: `rtk python -m pytest tests\unit\test_price_compare_feed_import.py -q`

Expected: feed normalization test passes.

### Task 4: Backend Signed Search Endpoint

**Files:**
- Create: `tests/unit/test_price_compare_auth.py`
- Create: `src/price_monitor/price_compare/auth.py`
- Modify: `src/price_monitor/api/v1/search.py`

**Interfaces:**
- Consumes: `verify_signed_request()` from `price_monitor.core.security`.
- Produces: FastAPI dependency `require_signed_request`.

- [ ] **Step 1: Write failing unsigned request test**

```python
from fastapi.testclient import TestClient

from price_monitor.main import create_app


def test_search_requires_hmac_signature_when_secret_configured(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_HMAC_SECRETS", "wp=test-secret")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/search",
        json={"query": "iphone", "city": "Москва", "limit": 10, "offset": 0},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_failed"
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk python -m pytest tests\unit\test_price_compare_auth.py -q`

Expected: route currently accepts unsigned requests or returns missing route before Task 1.

- [ ] **Step 3: Add HMAC dependency**

Read raw body once, verify headers, return `AuthenticationError` on failure, keep health endpoints public.

- [ ] **Step 4: Run auth tests**

Run: `rtk python -m pytest tests\unit\test_price_compare_auth.py tests\unit\test_service_shell.py -q`

Expected: auth tests and existing shell tests pass.

### Task 5: WordPress Settings And REST Proxy

**Files:**
- Create: `development/test/tests/PriceComparisonProxyRestTest.php`
- Create: `development/test/tests/PriceComparisonAdminSettingsTest.php`
- Create: `includes/price-comparison/class-cashback-price-comparison-client.php`
- Create: `includes/price-comparison/class-cashback-price-comparison-rest-controller.php`
- Create: `admin/class-cashback-price-comparison-admin.php`
- Modify: `cashback-plugin.php`

**Interfaces:**
- Produces: REST route `cashback/v1/price-comparison/search`.
- Produces options: `cashback_price_compare_enabled`, `cashback_price_compare_base_url`, `cashback_price_compare_hmac_secret`, `cashback_price_compare_timeout`.

- [ ] **Step 1: Write failing REST proxy registration test**

```php
public function test_price_comparison_search_route_is_registered(): void {
    $controller = new Cashback_Price_Comparison_REST_Controller();
    $controller->register_routes();

    $routes = rest_get_server()->get_routes();

    $this->assertArrayHasKey('/cashback/v1/price-comparison/search', $routes);
}
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonProxyRestTest.php`

Expected: class/file missing.

- [ ] **Step 3: Implement route, nonce/capability-safe settings, and signed client**

Use `wp_remote_post()` from PHP only. Do not localize base URL or secret to JavaScript. Sanitize base URL with `esc_url_raw`, timeout as integer `1..15`, secret stored as an option with no REST exposure.

- [ ] **Step 4: Run targeted tests**

Run: `rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonProxyRestTest.php development\test\tests\PriceComparisonAdminSettingsTest.php`

Expected: targeted tests pass.

### Task 6: WordPress Cashback Enrichment

**Files:**
- Create: `development/test/tests/PriceComparisonCashbackEnrichmentTest.php`
- Create: `includes/price-comparison/class-cashback-price-comparison-service.php`
- Modify: `includes/price-comparison/class-cashback-price-comparison-rest-controller.php`

**Interfaces:**
- Consumes: `Savello_Cashback_Internal_API_Service::resolve_direct_product_link()`.
- Produces: item fields `cashback_status`, `action_label`, `action_url`, `cashback_note`.

- [ ] **Step 1: Write failing enrichment test**

```php
public function test_cashback_available_item_uses_activation_button(): void {
    $service = new Cashback_Price_Comparison_Service(
        $this->fake_client_returning_one_item('https://ozon.ru/product/1'),
        $this->fake_cashback_service_returning_activation('https://example.test/go')
    );

    $result = $service->search('Москва', 'iphone', get_current_user_id());

    $this->assertSame('Активировать кэшбэк', $result['items'][0]['action_label']);
    $this->assertSame('https://example.test/go', $result['items'][0]['action_url']);
}
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonCashbackEnrichmentTest.php`

Expected: service class missing.

- [ ] **Step 3: Implement enrichment with cache**

Use a per-request in-memory cache keyed by normalized product URL. If cashback lookup fails, keep the item and return `Купить` plus `Кэшбэк не определён`.

- [ ] **Step 4: Run enrichment and link-checker tests**

Run: `rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonCashbackEnrichmentTest.php development\test\tests\LinkCheckerServiceTest.php`

Expected: new enrichment and existing link-checker tests pass.

### Task 7: WordPress User UI

**Files:**
- Create: `development/test/tests/PriceComparisonUserFormTest.php`
- Create: `tests/price-comparison-form.test.mjs`
- Create: `includes/price-comparison/class-cashback-price-comparison-account.php`
- Create: `assets/js/cashback-price-comparison.js`
- Create: `assets/css/cashback-price-comparison.css`
- Modify: `cashback-plugin.php`

**Interfaces:**
- Produces Woo account endpoint/menu item `price-comparison`.
- Produces localized JS config with `restUrl`, `nonce`, and Russian copy only.

- [ ] **Step 1: Write failing account form test**

```php
public function test_account_page_renders_required_city_and_query_fields(): void {
    $account = new Cashback_Price_Comparison_Account();

    ob_start();
    $account->render_page();
    $html = ob_get_clean();

    $this->assertStringContainsString('Сравнить цену', $html);
    $this->assertStringContainsString('name="city"', $html);
    $this->assertStringContainsString('name="query"', $html);
}
```

- [ ] **Step 2: Run test to verify RED**

Run: `rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonUserFormTest.php`

Expected: account class missing.

- [ ] **Step 3: Write failing JS rendering test**

```javascript
test('renders safe buy button when cashback is unavailable', async () => {
  const { renderItems } = await import('../assets/js/cashback-price-comparison.js');
  const root = document.createElement('div');
  renderItems(root, [{ title: '<b>iPhone</b>', action_label: 'Купить', action_url: 'https://shop.test/p/1' }]);
  assert.equal(root.querySelector('b'), null);
  assert.equal(root.querySelector('a').textContent, 'Купить');
});
```

- [ ] **Step 4: Run JS test to verify RED**

Run: `rtk node --test tests\price-comparison-form.test.mjs`

Expected: JS file missing.

- [ ] **Step 5: Implement account UI and safe renderer**

Use DOM APIs (`textContent`, `setAttribute`) instead of HTML string interpolation for product fields. Validate empty city/query client-side and server-side.

- [ ] **Step 6: Run UI tests**

Run: `rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonUserFormTest.php`

Run: `rtk node --test tests\price-comparison-form.test.mjs tests\cashback-link-checker.test.mjs`

Expected: new UI tests and existing link checker JS tests pass.

### Task 8: Verification, Security, Deploy Prep, And Browser Smoke

**Files:**
- Modify: `docs/development.md` if new commands are added.
- Modify plugin Obsidian notes only if current docs become stale.

**Interfaces:**
- Produces final deploy-ready branches and Russian report evidence.

- [ ] **Step 1: Run service gates**

Run:

```powershell
rtk python -m pytest
rtk python -m ruff check .
rtk python -m ruff format --check .
rtk python -m mypy
rtk docker compose config --quiet
rtk git diff --check
```

Expected: all pass or a specific environment limitation is recorded.

- [ ] **Step 2: Run plugin gates**

Run:

```powershell
rtk .\development\test\vendor\bin\phpunit.bat --bootstrap development\test\bootstrap.php development\test\tests\PriceComparisonProxyRestTest.php development\test\tests\PriceComparisonCashbackEnrichmentTest.php development\test\tests\PriceComparisonUserFormTest.php
rtk node --test tests\price-comparison-form.test.mjs tests\cashback-link-checker.test.mjs
rtk .\vendor\bin\phpcs.bat
rtk .\vendor\bin\phpstan.bat
rtk git diff --check
```

Expected: all pass or a specific environment limitation is recorded.

- [ ] **Step 3: Run security checks available without new heavy dependencies**

Run:

```powershell
rtk composer audit
rtk npm audit --audit-level=high
rtk python -m pip check
rtk git diff --check
rtk grep "api_key|secret|password|PRIVATE KEY|BEGIN RSA"
```

Expected: no unaddressed high-risk findings and no introduced secrets.

- [ ] **Step 4: Prepare test deploy**

Push both feature branches. Confirm CI quality gates. If the existing workflow deploys only `develop`, report that feature-branch test deploy needs either a temporary workflow dispatch or an explicit merge/push to `develop`.

- [ ] **Step 5: Browser smoke**

Verify as a normal user: menu `Сравнить цену`, empty field errors, successful fixture search, sorted cards, `Активировать кэшбэк`, `Купить`, not-found state, safe backend error state.

Verify as admin: page `Сравнение цен`, save settings, add/edit/disable store, logo selection path, import status display.

If browser automation is unavailable, run the closest HTTP/WP-CLI checks and record exactly what was not browser-verified.

## Self-Review

- Spec coverage: code study, branches, subagents, data-source feasibility, plan, TDD, WordPress UI/admin/proxy, service API/feed/search, cashback reuse, security, deploy prep, and browser smoke are mapped to tasks.
- Placeholder scan: no `TBD`, `TODO`, `implement later`, or unspecified test step remains.
- Type consistency: backend route uses `/api/v1/search` per pasted requirement; WordPress proxy uses `cashback/v1/price-comparison/search` to keep browser traffic inside WP.
