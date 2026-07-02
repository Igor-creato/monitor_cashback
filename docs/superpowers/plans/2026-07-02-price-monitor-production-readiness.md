# Price Monitor Production Readiness Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Keep RED -> GREEN TDD for every behavior change.

**Goal:** turn the current price-monitoring vertical slice into a production-ready service that can reliably monitor public product pages across several stores, with observable fetch jobs, source-specific policies, provider budgets, and safe secret handling.

**Decision:** build and own the monitoring core, but buy the hardest fetch/unblock layer first. Ready-made price-monitoring SaaS is useful for competitor intelligence, but it is a poor primary fit for our user watchlist, WordPress account UI, cashback activation path, HMAC contracts, per-user limits, and source-specific Russian marketplace UX. The cheapest reliable route is a hybrid: our scheduler, watchlist, matching, history, alerts, admin diagnostics, and adapters; managed unblocker/proxy providers for sources that do not return parseable public HTML to ordinary HTTP.

**Current blocker:** queue and API wiring were not the only issue. Live Joom responses previously showed a SPA shell and proof-of-work style API gating, so Joom needs a source-specific fetch strategy, not a small HTML selector tweak.

---

## Research Summary

### Proxy and unblocker providers

Use a tiered provider stack instead of betting on one vendor:

- **Primary affordable managed fetch:** Decodo Web Scraping API / Site Unblocker. Good first candidate for ecommerce pages where direct HTTP fails. Public pricing pages should be rechecked before purchase: <https://decodo.com/scraping/web/pricing>, <https://decodo.com/proxies/residential-proxies/pricing>.
- **Hard-target fallback:** Scrapfly. Useful when JavaScript rendering, anti-bot handling, and diagnostics matter more than raw price per request. Source: <https://scrapfly.io/>.
- **Alternative managed API:** Zyte API. Strong general scraping API with browser-rendering support and adaptive error handling. Sources: <https://docs.zyte.com/zyte-api/> and <https://docs.zyte.com/zyte-api/usage/browser.html>.
- **Enterprise benchmark, not first buy:** Bright Data Web Unlocker and Oxylabs Web Scraper API. Strong capabilities, but usually not the cheapest starting point. Sources: <https://brightdata.com/products/web-unlocker>, <https://oxylabs.io/products/scraper-api/web>.
- **Cheap raw proxy pool for experiments:** DataImpulse, Proxy-Seller, Webshare. Use only behind strict per-source budgets and diagnostics; raw proxies alone are less reliable than managed unblocker APIs. Sources: <https://dataimpulse.com/>, <https://proxy-seller.com/>, <https://www.webshare.io/>.
- **Challenge solvers:** CapMonster Cloud and 2Captcha/RuCaptcha can be kept as explicit later-stage provider plugins, not the default path. Any integration must avoid storing challenge tokens in logs or product records. Sources: <https://capmonster.cloud/>, <https://2captcha.com/>.

### Price monitoring and comparison services

- **Enterprise competitor-monitoring SaaS:** Prisync, DataWeave, Competera, Minderest. Good for catalog-level competitor intelligence, less suitable as the core engine for arbitrary user-submitted links and our WordPress/cashback UX. Sources: <https://prisync.com/>, <https://dataweave.com/>, <https://competera.ai/>, <https://www.minderest.com/>.
- **Marketplace/search APIs:** Keepa is useful for Amazon price history; SerpApi can help with Google Shopping discovery and comparison, but it is not a direct replacement for product-page monitoring in Russian stores. Sources: <https://keepa.com/#!api>, <https://serpapi.com/google-shopping-api>.
- **Crawler frameworks:** Scrapy/Crawlee are good foundations for our own fetch workers and browser crawlers, but they do not remove the need for proxies/unblockers on defended stores. Sources: <https://docs.scrapy.org/>, <https://crawlee.dev/python/docs/guides/playwright-crawler>.
- **Queue architecture:** Celery remains a good fit for scheduled fetch work, retries, and worker isolation. Source: <https://docs.celeryq.dev/>.

**Recommendation:** do not buy a full price-monitoring SaaS as the core. Implement our own monitoring service and integrate one managed unblocker first. Add raw proxy providers only after the job lifecycle, metrics, and per-source budgets are visible.

---

## Production Architecture

### Fetch ladder

Every source must define an ordered fetch ladder:

1. `official_or_structured_api` where a source provides a public, partner, seller, or approved API.
2. `direct_http` for parseable public HTML and JSON-LD.
3. `managed_unblocker` for protected public product pages.
4. `browser_provider` for JavaScript-rendered pages.
5. `raw_proxy_http` for controlled experiments and cheap fallback.
6. `quarantine` when the source blocks, exceeds budget, or parser confidence drops.

### Source policy

Add or extend per-source settings:

- `fetch_mode_order`
- `min_interval_seconds`
- `daily_request_budget`
- `daily_cost_budget_minor`
- `failure_threshold`
- `quarantine_until`
- `managed_provider_allowed`
- `browser_fallback_allowed`
- `raw_proxy_allowed`
- `challenge_provider_allowed`
- `parser_version`
- `parser_confidence_threshold`
- `diagnostic_sample_rate`

### Job lifecycle

Required lifecycle:

- `queued`
- `running`
- `ok`
- `failed`
- `quarantined`
- `dead_letter`

Each `FetchAttempt` must link to a `FetchJob`. Each job must expose enough diagnostics for the WordPress admin and backend logs to answer: which provider ran, why it failed, what it cost, whether a block/challenge happened, and when the source can be retried.

---

## Implementation Tasks

### Task 1: Finish the durable fetch-job lifecycle

Status: started in this branch.

- [x] Create an initial `FetchJob` when a watchlist item is added.
- [x] Pass `fetch_job_id` from create/refresh API into the Celery task.
- [x] Store `fetch_job_id` on `FetchAttempt`.
- [x] Move worker job status from `queued` to `running` to `ok` or `failed`.
- [ ] Add `status_reason`, `started_at`, `finished_at`, and `attempt_count` to `FetchJob`.
- [ ] Add a dead-letter path for unexpected worker exceptions.
- [ ] Add admin/read API fields for latest job and latest attempt.

### Task 2: Add provider abstraction

Files to create or extend:

- `src/price_monitor/domains/fetching/providers.py`
- `src/price_monitor/domains/fetching/managed_provider.py`
- `src/price_monitor/domains/fetching/provider_registry.py`
- `tests/unit/test_managed_fetch_provider.py`

Interfaces:

- `ManagedFetchProvider.fetch(url, source_policy, request_context) -> FetchPageResult`
- typed errors: `ProviderBlocked`, `ProviderQuotaExceeded`, `ProviderTimeout`, `ProviderBadResponse`
- normalized metadata: `provider_name`, `provider_request_id`, `cost_minor`, `rendered`, `challenge_detected`, `block_reason`

Acceptance:

- Unit tests use fake providers only.
- Provider credentials are secret references, never raw values in database rows, logs, attempts, or admin responses.
- Provider failures are recorded as attempts and mapped to stable statuses.

### Task 3: Integrate one managed provider first

Recommended first implementation:

- Decodo Site Unblocker or Web Scraping API as default provider.
- Scrapfly as configured fallback when Decodo fails with block/challenge/rendering failure.

Acceptance:

- Provider can be enabled per source.
- Provider has daily request and cost budgets.
- Provider result is normalized into the existing extraction pipeline.
- When budget is exceeded, source/job moves to `quarantined`, not infinite retry.

### Task 4: Build source adapters

Create source-specific adapters behind `ProductSourceAdapter.fetch_product`:

- `JoomAdapter`: treat current plain HTTP response as SPA shell. Try managed unblocker/browser strategy and parse either rendered product state, JSON-LD, meta tags, or discovered public product payload.
- `OzonAdapter`: keep buyer cart/favorites out of scope unless there is official/consented access. Product page monitoring may use the same public fetch ladder and source budgets.
- `WildberriesAdapter`: prefer structured public payloads if stable; fallback to managed provider.
- `GenericHtmlAdapter`: direct HTTP + JSON-LD/meta extraction for simple stores.

Acceptance:

- Each adapter returns `title`, `price_minor`, `currency`, `image_url`, `availability`, `canonical_url`, `parser_version`, `confidence`.
- Low-confidence parse is a failed attempt, not a false price update.
- Tests store real fixture snapshots with secrets/tokens stripped.

### Task 5: Add scheduler and source rate control

- Use Celery beat or a single scheduler worker to select due active watchlist items.
- Create jobs idempotently with logical keys.
- Enforce per-source `min_interval_seconds`.
- Enforce per-user and global max tracked products.
- Add jitter so all products for one source do not refresh at the same second.
- Stop scheduling when source is quarantined or daily budget is reached.

Acceptance:

- Duplicate due scans do not create duplicate jobs.
- A source can be paused from admin without deploy.
- Scheduler tests use frozen time and fake queue enqueue.

### Task 6: Add observability and admin diagnostics

Metrics:

- `fetch_jobs_total{source,status}`
- `fetch_attempts_total{source,strategy,provider,status,reason}`
- `fetch_provider_cost_minor_total{source,provider}`
- `fetch_quarantine_total{source,reason}`
- `fetch_parse_confidence_bucket{source,parser_version}`

Admin diagnostics:

- source status
- latest job status
- latest attempt strategy/provider
- last block reason
- current quarantine state
- daily request/cost usage
- parser version and confidence

Acceptance:

- Admin never shows raw provider tokens, proxy credentials, raw cookies, or challenge tokens.
- Logs include request ids and provider request ids only.

### Task 7: Product matching and comparison

Implement comparison only after reliable single-product monitoring works:

- normalize title, brand, model, size, color, SKU/article where available
- source-specific SKU extraction
- candidate matching table with confidence
- manual admin override for false matches
- optional search provider such as SerpApi for Google Shopping discovery

Acceptance:

- No automatic cross-store price comparison is shown below confidence threshold.
- User can still monitor a single link without comparison data.

### Task 8: Production deployment gates

Backend gates:

```powershell
rtk py -m pytest
rtk ruff check .
rtk ruff format --check .
rtk mypy
rtk py -m pip check
rtk docker compose config --quiet
rtk git diff --check
```

Runtime smoke:

- migrations apply
- health endpoints pass
- source setup works
- add supported product creates watchlist item and initial job
- duplicate add returns `duplicate_watchlist_item`
- manual refresh creates one job and one queue task
- worker updates job, attempt, product, and price history
- admin diagnostics show latest status without secrets
- source quarantine works when provider budget is exceeded
- alert dispatch works when price crosses target

### Task 9: Rollout sequence

1. Deploy lifecycle and diagnostics with providers disabled.
2. Enable direct HTTP monitoring for one easy source.
3. Enable managed provider for one hard source with a small daily budget.
4. Verify costs and block rates for 24-48 hours.
5. Add the next source only after the previous source has stable success rate, cost, and parser confidence.
6. Enable comparison/search features only after single-product monitoring is stable.

### Task 10: Explicit non-goals for the first production release

- No marketplace password storage.
- No unapproved raw browser session capture.
- No raw provider credentials in database/logs/admin UI.
- No buyer cart/favorites automation without official, partner, or explicitly consented access.
- No automatic cross-store product matching below confidence threshold.
- No unlimited retries against protected stores.
