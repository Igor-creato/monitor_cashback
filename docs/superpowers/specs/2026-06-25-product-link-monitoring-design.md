# Product Link Monitoring Production Design

Date: 2026-06-25
Status: design approved for option 1; implementation not started
Repository: `F:\cash-back\monitor_cashback`
Service: `price-monitor`

## Scope

This design covers only product monitoring by a user-provided product URL.

In scope:

- adding a product URL to the user's watchlist;
- normalizing and allowlisting product URLs for supported stores;
- fetching product title, current price, image, and availability when available;
- saving price history;
- exposing price chart data through the existing chart endpoint;
- generating price-change notifications through the existing notification
  pipeline;
- adding a modular store adapter registry;
- reporting per-store readiness and unsupported reasons.

Out of scope:

- cart and favorites monitoring;
- product search;
- cross-store comparison;
- marketplace login, password, cookie, or token capture;
- captcha solving, fingerprint bypass, access-control bypass, or aggressive
  anti-bot evasion;
- implementing paid proxy services or paid third-party scraping services.

## Existing Foundation

The existing backend already has the main product-link monitoring pipeline:

- `app.api.watchlist` accepts HMAC-protected watchlist requests.
- `app.services.watchlist` creates `TrackedProduct` and
  `UserProductSubscription` rows from a normalized URL.
- `app.services.fetch_jobs` deduplicates queued fetch jobs.
- `app.services.multistage_fetch_executor` selects feed, HTTP, proxy, browser,
  or quarantine strategies and records fetch attempts/source health.
- `app.services.fetch_job_runner` updates product fields, stores images, writes
  `PriceHistory`, resolves cashback, and evaluates price alerts.
- `app.services.price_chart` builds chart data from price history.
- `app.services.notifications` creates and dispatches deduplicated price alerts.

The implementation should extend this path instead of creating a parallel
product-monitoring module.

## Store Support Policy

Every requested store gets an explicit registry entry with one of these states:

- `supported`: a safe implementation path exists and tests cover it.
- `requires_access`: official API/feed/session/proxy/legal approval is needed.
- `unsupported`: no stable safe path is currently available.

The service must not silently treat an unknown or risky store as supported.
Unsupported or access-gated stores fail closed when a user submits their URL and
are visible in readiness/reporting with a human-readable reason.

Requested store list:

- Wildberries
- Ozon
- Yandex Market
- DNS
- Samokat
- VkusVill
- Vseinstrumenti
- Yandex Lavka
- Gold Apple
- Lamoda
- ETM
- Pyaterochka
- Citilink
- Kuper
- Yandex Eda
- Apteka.ru
- M.Video
- Petrovich
- Magnit
- Lemana Pro

## Architecture

### Store Registry

Add a small product-link monitoring registry under the existing backend code,
for example:

```text
app/product_monitoring/
  __init__.py
  registry.py
  adapters/
    base.py
    generic_structured_data.py
    wildberries.py
    store-specific adapter files
```

The registry owns:

- store code;
- display name;
- host patterns;
- URL normalization rules;
- support state;
- fetch/extraction strategy hints;
- unsupported or access-required reason;
- optional adapter factory.

Adding a store should mean adding a registry entry or adapter file, not editing
the fetch runner, watchlist service, chart service, or notification service.

### URL Normalization

`app.core.product_url_normalizer.normalize_product_url()` remains the public
normalization function used by watchlist creation. Internally it can delegate to
the new registry.

Normalization must:

- accept only `https`;
- match exact approved hostnames or subdomains from the registry;
- extract stable external product identity from path/query;
- remove tracking parameters;
- preserve safe region/variant identity where applicable;
- never perform network requests;
- fail closed for unknown or unsupported sources.

### Extraction Adapters

Adapters return the existing `PriceFetchResult` shape through the current
fetch pipeline. The preferred order is:

1. official API or feed when approved and configured;
2. structured public page data, such as JSON-LD, OpenGraph, embedded product
   JSON, or stable server-rendered HTML;
3. browser-rendered HTML only when the site requires JavaScript and source
   policy allows it;
4. `requires_access` or `unsupported` if the site needs credentials, a paid
   service, proxy-only access, or hits anti-bot/captcha pressure.

The existing multistage fetch executor remains responsible for retries,
timeouts, proxy option hooks, fetch attempts, source health, quarantine, and
metrics. Adapters must not implement bypass logic.

### Data Flow

1. WordPress sends a signed watchlist add request.
2. FastAPI normalizes the product URL through the registry.
3. If the store is supported, the existing watchlist service creates or reuses
   `TrackedProduct` and `UserProductSubscription`.
4. A fetch job is queued through the existing scheduler/job path.
5. The fetch pipeline runs the selected strategy and adapter.
6. A successful fetch updates title, price, image, availability, and status.
7. The price history repository writes a price point.
8. The existing chart endpoint reads price history.
9. The existing notification service evaluates price-drop, target-price, new
   minimum, and back-in-stock events.

## Error Handling and Observability

Store-level errors must map to existing safe status labels where possible:

- `unsupported_source`
- `source_requires_access`
- `source_disabled_or_quarantined`
- `http_403`
- `http_429`
- `timeout`
- `parser_error`
- `captcha_detected`
- `price_not_found`
- `bad_content`
- `source_unavailable`
- `browser_unavailable`

The implementation should keep using existing fetch attempts, source health,
quarantine, and metrics services. New readiness reporting can be a static or
admin-safe backend report that contains only store code, display name, state,
strategy, and reason. It must not expose secrets, cookies, tokens, raw private
HTML, or proxy credentials.

## Testing Strategy

Use strict TDD for each implementation slice:

1. Start with failing tests for registry and URL normalization.
2. Add adapter tests with local fixtures and fake network/browser transports.
3. Add integration tests that prove a supported URL can create a watchlist
   item, fetch product data, write price history, expose chart data, and create
   notification events.
4. Add negative tests for unsupported, access-required, captcha, 403, 429,
   timeout, parser failure, and price-not-found paths.
5. Keep cart/favorites, search, and comparison tests untouched except as
   regression boundaries.

Verification boundary for implementation:

- targeted product-link monitoring tests;
- related watchlist/fetch/history/chart/notification tests;
- `python -m ruff check .`;
- `python -m ruff format --check .`;
- coverage report proving at least 80 percent coverage for new/changed code;
- dependency/security audit for added packages;
- Docker Compose smoke when runtime dependencies change;
- CI workflow check if code changes affect CI configuration.

## Pre-Code Gate Findings

Live checks on 2026-06-25:

- `price-parser` latest PyPI release is `0.5.1`, released 2026-03-19, supports
  Python 3.13 and 3.14, uses BSD-3-Clause, and has no OSV findings in the quick
  package query. It is a good candidate for price text parsing if the current
  in-house normalizer becomes insufficient.
- `extruct` latest PyPI release is `0.18.0`, released 2024-11-08, supports
  JSON-LD, Microdata, OpenGraph, Microformats, RDFa, and Dublin Core extraction,
  and has no OSV findings in the quick package query. Because the package is
  marked beta and its latest release is older, prefer using the existing
  BeautifulSoup extractor first and add `extruct` only if structured-data
  coverage needs it.
- Yandex Market has official seller APIs for prices and stocks, but the
  documented methods require API-key scoped seller access and are not a public
  consumer product-price API.
- Ozon official documentation found during the gate is seller/help oriented;
  consumer product-link monitoring still needs a separate source approval
  before using any non-public/private API path.

## Documentation and Reporting

Implementation must update a production readiness report or roadmap entry after
each iteration. The report should list:

- completed product-link monitoring capabilities;
- store support state for all 20 requested stores;
- unsupported or access-required reason per store;
- tests and checks run;
- remaining gaps.

The canonical Obsidian Monitor Cashback note must be updated after code changes
that affect API, architecture, DB, Redis/queue behavior, deployment, or source
support posture.

## Implementation Order

1. Add registry and URL normalization tests for all 20 stores.
2. Implement registry-backed normalization with fail-closed states.
3. Add readiness/reporting surface for store support states.
4. Add generic structured-data extraction fixture tests.
5. Implement the first safe supported adapters using fixtures only.
6. Wire adapters into the existing fetch executor without changing cart,
   favorites, search, or comparison code.
7. Add end-to-end product-link tests through watchlist, fetch, history, chart,
   and notifications.
8. Run the full verification boundary and update readiness documentation.

## Open Implementation Constraints

- Stores requiring official seller API keys, user sessions, legal approval,
  proxy-only access, or manual source approval must be marked `requires_access`
  until those inputs exist.
- Stores that trigger captcha, bot detection, fingerprint challenges, or
  unstable private APIs must be marked `unsupported` or quarantined rather than
  retried aggressively.
- Public structured page data may be used only when it is available without
  credentials and can be tested from fixtures.
- Browser automation is allowed only as a configured fetch strategy and never
  as captcha or anti-bot bypass.
