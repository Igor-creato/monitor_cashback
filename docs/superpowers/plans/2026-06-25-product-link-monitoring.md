# Product Link Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build production-ready product monitoring by URL without changing cart/favorites monitoring, product search, or cross-store comparison.

**Architecture:** Extend the existing watchlist/fetch/history/chart/notification path with a product-monitoring store registry. URL normalization delegates to registry entries, while the existing fetch executor remains responsible for retries, attempts, health, quarantine, and metrics.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, pytest, Ruff, existing BeautifulSoup-based extraction, existing Celery/fetch pipeline.

## Global Constraints

- Use only `F:\cash-back\monitor_cashback` and `price-monitor/backend` for service changes.
- Do not modify cart/favorites sync, product search, or comparison modules except as read-only regression context.
- Keep all commands prefixed with `rtk`.
- Follow TDD: write failing targeted tests before implementation.
- Do not add marketplace password, cookie, token, captcha bypass, fingerprint bypass, or aggressive anti-bot logic.
- Mark stores that need API keys, user sessions, paid proxy/scraper, legal approval, or unstable private APIs as `requires_access` or `unsupported`.
- Keep external HTTP mocked/faked in tests unless an explicit server smoke is being run.
- Update readiness documentation after each implementation iteration.

---

### Task 1: Store Registry and URL Normalization

**Files:**
- Create: `price-monitor/backend/app/product_monitoring/__init__.py`
- Create: `price-monitor/backend/app/product_monitoring/registry.py`
- Modify: `price-monitor/backend/app/core/product_url_normalizer.py`
- Modify: `price-monitor/backend/app/tests/test_product_url_normalizer.py`
- Create: `price-monitor/backend/app/tests/test_product_monitoring_registry.py`
- Create: `price-monitor/docs/product-link-monitoring-readiness.md`

**Interfaces:**
- Produces: `StoreSupportState = Literal["supported", "requires_access", "unsupported"]`
- Produces: `ProductUrlPattern(path_prefix: str, id_pattern: str | None = None)`
- Produces: `StoreRegistryEntry`
- Produces: `StoreUrlNormalization`
- Produces: `get_store_registry() -> tuple[StoreRegistryEntry, ...]`
- Produces: `get_store_entry_by_host(hostname: str) -> StoreRegistryEntry | None`
- Produces: `normalize_store_product_url(url: str) -> StoreUrlNormalization`
- Consumes: `NormalizedProductUrl` and `UnsupportedSourceError` from `app.core.product_url_normalizer`

- [ ] **Step 1: Write failing registry tests**

Add tests to `price-monitor/backend/app/tests/test_product_monitoring_registry.py`:

```python
from app.product_monitoring.registry import (
    get_store_entry_by_host,
    get_store_registry,
    normalize_store_product_url,
)

EXPECTED_STORE_CODES = {
    "wildberries",
    "ozon",
    "yandex_market",
    "dns",
    "samokat",
    "vkusvill",
    "vseinstrumenti",
    "yandex_lavka",
    "goldapple",
    "lamoda",
    "etm",
    "pyaterochka",
    "citilink",
    "kuper",
    "yandex_eda",
    "apteka_ru",
    "mvideo",
    "petrovich",
    "magnit",
    "lemana_pro",
}


def test_registry_contains_all_requested_store_codes() -> None:
    entries = get_store_registry()

    assert {entry.code for entry in entries} == EXPECTED_STORE_CODES
    assert len(entries) == len(EXPECTED_STORE_CODES)


def test_registry_entries_have_safe_support_metadata() -> None:
    for entry in get_store_registry():
        assert entry.display_name
        assert entry.hostnames
        assert entry.support_state in {"supported", "requires_access", "unsupported"}
        assert entry.fetch_strategy in {"structured_data", "official_api", "browser", "none"}
        if entry.support_state != "supported":
            assert entry.reason


def test_host_lookup_supports_subdomains_without_network_calls() -> None:
    entry = get_store_entry_by_host("www.wildberries.ru")

    assert entry is not None
    assert entry.code == "wildberries"


def test_supported_wildberries_url_normalizes_to_stable_identity() -> None:
    result = normalize_store_product_url(
        "https://www.wildberries.ru/catalog/123456/detail.aspx"
        "?utm_source=ad&ref=partner&targetUrl=EX"
    )

    assert result.source == "wildberries"
    assert result.external_product_id == "123456"
    assert result.canonical_url == "https://www.wildberries.ru/catalog/123456/detail.aspx?targetUrl=EX"
    assert result.region_code == "default"
    assert result.variant_hash is None


def test_access_required_store_fails_closed_with_reason() -> None:
    try:
        normalize_store_product_url("https://www.ozon.ru/product/test-123/")
    except ValueError as exc:
        assert "source_requires_access" in str(exc)
    else:
        raise AssertionError("Ozon must fail closed until source approval exists")
```

- [ ] **Step 2: Run registry tests to verify RED**

Run:

```powershell
rtk python -m pytest app/tests/test_product_monitoring_registry.py -q
```

Expected: FAIL with import error for `app.product_monitoring.registry`.

- [ ] **Step 3: Write failing normalizer integration tests**

Append to `price-monitor/backend/app/tests/test_product_url_normalizer.py`:

```python
def test_normalizer_accepts_supported_registry_source() -> None:
    result = normalize_product_url("https://www.wildberries.ru/catalog/123456/detail.aspx")

    assert result.source == "wildberries"
    assert result.external_product_id == "123456"
    assert result.canonical_url == "https://www.wildberries.ru/catalog/123456/detail.aspx"


def test_normalizer_fails_closed_for_requires_access_registry_source() -> None:
    with pytest.raises(UnsupportedSourceError, match="source_requires_access"):
        normalize_product_url("https://www.ozon.ru/product/test-123/")
```

- [ ] **Step 4: Run normalizer tests to verify RED**

Run:

```powershell
rtk python -m pytest app/tests/test_product_url_normalizer.py::test_normalizer_accepts_supported_registry_source app/tests/test_product_url_normalizer.py::test_normalizer_fails_closed_for_requires_access_registry_source -q
```

Expected: FAIL because registry-backed normalization is not implemented.

- [ ] **Step 5: Implement registry models and entries**

Create `price-monitor/backend/app/product_monitoring/__init__.py`:

```python
"""Product-link monitoring registry and adapters."""
```

Create `price-monitor/backend/app/product_monitoring/registry.py` with frozen dataclasses, registry entries for all 20 stores, host lookup, support-state validation, tracking query stripping, and URL normalization. Mark `wildberries` as `supported` for the first safe fixture-backed iteration. Mark stores needing source approval/API/session/proxy/legal review as `requires_access` with explicit reasons.

- [ ] **Step 6: Delegate `normalize_product_url()` to registry first**

Modify `price-monitor/backend/app/core/product_url_normalizer.py` so it calls `normalize_store_product_url(url)` before falling back to the existing local demo sources. Convert registry `ValueError` to `UnsupportedSourceError` while preserving safe reason text.

- [ ] **Step 7: Add readiness report**

Create `price-monitor/docs/product-link-monitoring-readiness.md` with all 20 store codes, display names, support state, first safe strategy, and reason for every non-supported store.

- [ ] **Step 8: Run Task 1 GREEN checks**

Run:

```powershell
rtk python -m pytest app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py -q
rtk python -m ruff check app/product_monitoring app/core/product_url_normalizer.py app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py
rtk python -m ruff format --check app/product_monitoring app/core/product_url_normalizer.py app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py
```

Expected: PASS.

### Task 2: Readiness Surface and Watchlist Fail-Closed Coverage

**Files:**
- Modify: `price-monitor/backend/app/services/watchlist.py`
- Modify: `price-monitor/backend/app/tests/test_watchlist_api.py`
- Modify: `price-monitor/docs/product-link-monitoring-readiness.md`

**Interfaces:**
- Consumes: `normalize_product_url(url: str) -> NormalizedProductUrl`
- Produces: no new public API in this task

- [ ] **Step 1: Add failing watchlist tests for registry source behavior**

Add tests proving a supported registry source can be added and a `requires_access` source returns HTTP 400 with the safe reason preserved in service-level exception text.

- [ ] **Step 2: Run watchlist tests to verify RED**

Run:

```powershell
rtk python -m pytest app/tests/test_watchlist_api.py::test_registry_supported_source_can_be_added app/tests/test_watchlist_api.py::test_registry_requires_access_source_is_rejected -q
```

Expected: FAIL until test helpers and error mapping are updated.

- [ ] **Step 3: Implement minimal service/API behavior**

Keep the public watchlist response shape unchanged. Ensure unsupported/access-required registry errors become `UnsupportedWatchlistSourceError` and are logged only as safe text without URL secrets.

- [ ] **Step 4: Run Task 2 GREEN checks**

Run:

```powershell
rtk python -m pytest app/tests/test_watchlist_api.py app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py -q
rtk python -m ruff check app/services/watchlist.py app/api/watchlist.py app/tests/test_watchlist_api.py
rtk python -m ruff format --check app/services/watchlist.py app/api/watchlist.py app/tests/test_watchlist_api.py
```

Expected: PASS.

### Task 3: Fixture-Based Structured Data Adapter

**Files:**
- Create: `price-monitor/backend/app/product_monitoring/adapters/__init__.py`
- Create: `price-monitor/backend/app/product_monitoring/adapters/base.py`
- Create: `price-monitor/backend/app/product_monitoring/adapters/generic_structured_data.py`
- Create: `price-monitor/backend/app/tests/test_product_monitoring_structured_data_adapter.py`
- Modify: `price-monitor/backend/app/services/multistage_fetch_executor.py`
- Modify: `price-monitor/docs/product-link-monitoring-readiness.md`

**Interfaces:**
- Produces: `ProductPageAdapter.extract(content: str | bytes | dict, fetched_at: datetime) -> PriceFetchResult`
- Consumes: existing `PriceFetchResult`
- Consumes: registry `StoreRegistryEntry`

- [ ] **Step 1: Add failing adapter tests with local fixtures**

Write tests that pass static HTML containing JSON-LD Product data and assert title, price, currency, image, and availability extraction.

- [ ] **Step 2: Run adapter tests to verify RED**

Run:

```powershell
rtk python -m pytest app/tests/test_product_monitoring_structured_data_adapter.py -q
```

Expected: FAIL with missing adapter module.

- [ ] **Step 3: Implement generic structured-data adapter**

Use BeautifulSoup and `json.loads` to parse local JSON-LD scripts. Do not add `extruct` in this task. Map schema.org `Product.name`, `Product.image`, `offers.price`, `offers.priceCurrency`, and `offers.availability` to `PriceFetchResult`.

- [ ] **Step 4: Wire adapter into fetch executor behind registry strategy**

Add a narrow branch so registry entries with `fetch_strategy == "structured_data"` can parse fetched HTML through the adapter. Preserve existing schema resolver behavior for demo/test sources.

- [ ] **Step 5: Run Task 3 GREEN checks**

Run:

```powershell
rtk python -m pytest app/tests/test_product_monitoring_structured_data_adapter.py app/tests/test_multistage_fetch_executor.py -q
rtk python -m ruff check app/product_monitoring app/services/multistage_fetch_executor.py app/tests/test_product_monitoring_structured_data_adapter.py
rtk python -m ruff format --check app/product_monitoring app/services/multistage_fetch_executor.py app/tests/test_product_monitoring_structured_data_adapter.py
```

Expected: PASS.

### Task 4: Product-Link End-to-End Proof and Verification

**Files:**
- Create: `price-monitor/backend/app/tests/test_product_link_monitoring_e2e.py`
- Modify: `price-monitor/docs/product-link-monitoring-readiness.md`
- Modify: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\knowledge\integrations\monitor-cashback.md`

**Interfaces:**
- Consumes: registry-backed normalization
- Consumes: structured-data adapter
- Consumes: existing watchlist, fetch job runner, price history, chart, notification services

- [ ] **Step 1: Add failing E2E test with fake fetch transport**

Write one local test that adds a supported URL, runs a fake fetch result through the existing job runner, asserts product fields, one price history point, chart series, and a notification event for a configured target price.

- [ ] **Step 2: Run E2E test to verify RED**

Run:

```powershell
rtk python -m pytest app/tests/test_product_link_monitoring_e2e.py -q
```

Expected: FAIL until the supporting wiring is complete.

- [ ] **Step 3: Implement minimal wiring fixes**

Only change product-link monitoring code paths. Do not edit cart/favorites sync, search, or comparison modules.

- [ ] **Step 4: Run full local verification boundary**

Run from `price-monitor/backend`:

```powershell
rtk python -m pytest app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py app/tests/test_product_monitoring_structured_data_adapter.py app/tests/test_product_link_monitoring_e2e.py app/tests/test_watchlist_api.py app/tests/test_fetch_job_runner.py app/tests/test_price_chart_api.py app/tests/test_notifications_service.py -q
rtk python -m pytest -q
rtk python -m ruff check .
rtk python -m ruff format --check .
```

Expected: PASS or clearly separated unrelated baseline failure.

- [ ] **Step 5: Commit and push**

Run from repo root:

```powershell
rtk git status --short --untracked-files=all
rtk git add price-monitor/backend/app/product_monitoring price-monitor/backend/app/core/product_url_normalizer.py price-monitor/backend/app/services/multistage_fetch_executor.py price-monitor/backend/app/tests price-monitor/docs/product-link-monitoring-readiness.md "F:/wamp64/www/kash-back/wp-content/plugins/cash-back/obsidian/knowledge/integrations/monitor-cashback.md"
rtk git commit -m "feat: add product link monitoring registry"
rtk git push
```

Expected: commit and push succeed.

- [ ] **Step 6: Test server smoke without stopping other services**

Use the approved SSH target:

```powershell
rtk ssh -i F:/cash-back/.test_ssh/admin_vps_claude -p 56789 igor@5.35.124.64 "cd /home/igor/monitoring-cashback && git status --short && git rev-parse --short HEAD"
```

If the server is not on the pushed commit, stop and ask before running `git pull`, migrations, restarts, or Docker Compose commands with side effects.
