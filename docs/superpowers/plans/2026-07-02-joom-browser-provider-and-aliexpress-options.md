# Joom Browser Provider And AliExpress Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-specific Joom browser/provider acquisition path and document the safe AliExpress API/provider choices.

**Architecture:** The existing `FetchPipeline` remains the orchestration layer. Direct HTTP extraction gains OpenGraph product metadata support, and the worker can optionally pass a source-aware browser fetcher that delegates Joom URLs to a configured rendered-HTML provider.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, httpx, pytest, ruff, mypy.

## Global Constraints

- Always run shell commands with `rtk`.
- Use RED -> GREEN TDD for behavior changes.
- Do not implement CAPTCHA bypass, fingerprint bypass, raw cookies, or marketplace login flows.
- Unit tests must use fake transports/providers and must not call real browsers or marketplaces.
- Secrets must come from environment settings and must not be logged.
- Keep AliExpress disabled until an official API or approved provider is selected and verified.

---

### Task 1: OpenGraph Product Metadata Extraction

**Files:**
- Modify: `src/price_monitor/domains/fetching/extraction.py`
- Test: `tests/unit/test_fetch_extraction.py`

**Interfaces:**
- Consumes: `extract_product_data(html: str, *, fallback_currency: str) -> FetchedProductData | None`
- Produces: OpenGraph meta fallback using `og:title`, `og:image`, `product:price:amount`, and `product:price:currency`.

- [ ] **Step 1:** Write a failing test with Joom-like OpenGraph product meta tags.
- [ ] **Step 2:** Run `rtk python -m pytest tests/unit/test_fetch_extraction.py::test_extract_product_data_from_open_graph_product_meta -q` and verify RED.
- [ ] **Step 3:** Add a small meta-tag parser and fallback extraction path.
- [ ] **Step 4:** Rerun the targeted test and existing extraction tests.

### Task 2: Joom Rendered HTML Provider Fetcher

**Files:**
- Create: `src/price_monitor/domains/fetching/source_browser_fetcher.py`
- Modify: `src/price_monitor/core/config.py`
- Test: `tests/unit/test_source_browser_fetcher.py`

**Interfaces:**
- Produces: `BrowserProviderUnavailableError`
- Produces: `HttpRenderedHtmlProvider.render(url: str, source_domain: str, wait_selector: str | None, proxy_url: str | None) -> FetchPageResult`
- Produces: `JoomBrowserProviderFetcher.fetch(url: str, proxy_url: str | None) -> FetchPageResult`
- Produces: `SourceAwareBrowserFetcher.fetch(url: str, proxy_url: str | None) -> FetchPageResult`
- Produces: `build_source_browser_fetcher(settings: Settings) -> ProductPageFetcher | None`

- [ ] **Step 1:** Write failing fake-transport tests for provider payload, token header, response mapping, Joom dispatch, and no-provider behavior.
- [ ] **Step 2:** Run `rtk python -m pytest tests/unit/test_source_browser_fetcher.py -q` and verify RED.
- [ ] **Step 3:** Implement the provider/fetcher module with lazy, environment-driven construction.
- [ ] **Step 4:** Rerun targeted tests.

### Task 3: Worker Wiring

**Files:**
- Modify: `src/price_monitor/workers/tasks/fetch_product.py`
- Test: `tests/unit/test_fetch_pipeline.py`

**Interfaces:**
- Consumes: `build_source_browser_fetcher(settings)`
- Produces: worker `FetchPipeline(..., browser_fetcher=...)` wiring when a provider is configured.

- [ ] **Step 1:** Write a failing worker test that monkeypatches `build_source_browser_fetcher` and asserts the worker passes its result into `FetchPipeline`.
- [ ] **Step 2:** Run the targeted test and verify RED.
- [ ] **Step 3:** Add the worker wiring without changing queue behavior.
- [ ] **Step 4:** Rerun targeted worker tests.

### Task 4: AliExpress Provider Options Documentation

**Files:**
- Create: `docs/aliexpress-provider-options.md`

**Interfaces:**
- Produces: documented decision matrix for official Affiliate API, Piloterr, Oxylabs, ScrapingBee, Apify, and disabled fallback.

- [ ] **Step 1:** Record the official API and provider options with links, required credentials, pros, cons, and recommendation.
- [ ] **Step 2:** Run `rtk git diff --check`.

### Task 5: Verification And Server Smoke

**Files:**
- Modify only if verification exposes defects.

**Interfaces:**
- Produces: local evidence and test-server evidence.

- [ ] **Step 1:** Run `rtk python -m pytest tests/unit/test_fetch_extraction.py tests/unit/test_source_browser_fetcher.py tests/unit/test_fetch_pipeline.py -q`.
- [ ] **Step 2:** Run `rtk python -m pytest -q`.
- [ ] **Step 3:** Run `rtk python -m ruff check .`, `rtk python -m ruff format --check .`, `rtk python -m mypy`, `rtk docker compose config --quiet`, and `rtk git diff --check`.
- [ ] **Step 4:** Deploy through the existing develop workflow only after local gates pass.
- [ ] **Step 5:** On the test server, keep Joom disabled unless a rendered provider URL is configured; verify Citilink still works and Joom reports `monitoring_unavailable` or works through configured provider.
