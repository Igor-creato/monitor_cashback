# Price Monitor Source Adapters Production Design

## Goal

Bring the price monitoring service to a working test-stage state where a
website user can add an individual product URL from AliExpress, Citilink, Joom,
Wildberries, Ozon, and Yandex Market and receive a product card with title,
image, current price, optional rating, price chart, and clear loading or error
state.

This design keeps the current split:

- `F:\cash-back\monitor_cashback` owns the FastAPI service, worker, source
  policies, URL validation, fetching, extraction, price history, diagnostics,
  CI, and test-server deployment.
- `F:\wamp64\www\kash-back\wp-content\plugins\cash-back` owns the WooCommerce
  account UI, WordPress REST proxy, admin forms, nonce/capability checks, and
  cashback activation link reuse.

## Non-Negotiable Boundaries

- Use RED -> GREEN TDD for every behavior change.
- Do not store marketplace passwords, unapproved raw cookies, raw browser
  sessions, provider secrets, proxy credentials, or challenge tokens in the
  database, logs, docs, screenshots, fixtures, or git.
- Provider credentials are configured through server-managed runtime secrets or
  secret references. Admin and diagnostics may show only configured booleans,
  provider names, request ids, costs, and redacted secret references.
- If a source needs Decodo or another managed unblocker account, API key, trial,
  or paid plan to continue, stop and report exactly: "Нужно подключение Decodo",
  which credential or activation is needed, why, and the minimal trial or tariff
  sufficient for the next check.
- Do not build buyer cart or favorites automation for Ozon, Wildberries, Yandex
  Market, or any marketplace without official, partner, or explicitly consented
  access. This goal is only public product-page monitoring.
- All tests for fetchers, providers, and source adapters use fake providers or
  sanitized fixtures. No test performs live marketplace traffic.
- Existing HMAC, idempotency, activation redirect, and WordPress proxy contracts
  are preserved.

## Approved Approach

Use a phased hybrid adapter architecture.

1. Finish the backend foundation: product URL classification, fetch job
   lifecycle diagnostics, attempt metadata, extraction confidence, and product
   card/history contracts.
2. Add source-specific adapters behind one registry and one fetch ladder. Each
   adapter validates that a URL is an individual product page before the
   watchlist accepts it.
3. Use direct or structured public data where it is stable. Escalate to
   browser/managed provider only through explicit per-source policy.
4. Keep the WordPress UI as the existing account-page proxy/card shell, adding
   only the error mappings and diagnostics fields required by the backend
   contracts.
5. Deploy only after local gates are green, then verify GitHub Actions,
   read-only server health/logs, and frontend smoke with a test user.

This is preferred over a single generic HTML parser because recent evidence
shows protected stores return SPA shells, CAPTCHA, proof-of-work, or incomplete
HTML. A generic parser remains useful only for simple non-mandatory stores; the
six required stores must route through their source adapters.

## Backend Architecture

### Source URL Classifier

Add a source-aware classifier separate from generic SSRF URL safety.

Responsibilities:

- Preserve `validate_public_product_url()` for scheme, host, local/private IP,
  redirect safety inputs, tracking-query cleanup, canonical URL, and URL hash.
- Add a product-page classifier that returns:
  - `source_domain`
  - `canonical_url`
  - `canonical_url_hash`
  - `source_product_id` when extractable
  - `is_product_url`
  - stable `error_code`
  - Russian-safe `message`
- Reject home, category, search, cart, favorites, storefront, seller, and other
  non-product pages before creating a `Product` or `WatchlistItem`.

Initial error codes:

- `unsupported_store`
- `monitoring_unavailable`
- `not_product_url`
- `unsafe_url`
- `source_product_id_missing`
- `source_url_pattern_unsupported`

Store-specific product URL acceptance:

- AliExpress: accept item paths such as `/item/<numeric-id>.html` on configured
  AliExpress domains; reject search, category, cart, favorites, and storefront.
- Citilink: accept product detail paths that contain a terminal numeric product
  id; reject catalog/search/brand pages.
- Joom: accept `/products/<product-id>` with optional locale prefix; reject
  search/category/home/storefront.
- Wildberries: accept product detail paths with numeric nm id; reject catalog,
  seller, basket, favorites, and search pages.
- Ozon: accept product detail paths with numeric SKU in the path or query when
  stable; reject category, search, cart, favorites, seller, and brand pages.
- Yandex Market: accept product/model/card paths with stable product/model
  identity; reject search, catalog, cart, favorites, shop pages, and reviews-only
  pages.

### Adapter Registry

Create source adapters under `src/price_monitor/domains/fetching/sources/`.

Required adapters:

- `AliExpressAdapter`
- `CitilinkAdapter`
- `JoomAdapter`
- `WildberriesAdapter`
- `OzonAdapter`
- `YandexMarketAdapter`
- `GenericHtmlAdapter`

Shared interface:

```python
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

class SourceAdapter(Protocol):
    source_domain: str

    def classify_url(self, raw_url: str) -> ProductUrlClassification:
        ...

    def fetch_product(self, context: FetchContext) -> SourceFetchResult:
        ...
```

The adapter owns source-specific parsing and product identity rules. The
pipeline owns job/attempt persistence, strategy ordering, confidence gating,
price history, notifications, and diagnostics.

### Fetch Ladder

Each source has an ordered ladder:

1. `direct_http`
2. `structured_endpoint`
3. `browser_provider`
4. `managed_unblocker_provider`
5. `quarantined`
6. `failed`

The effective order is stored in source policy/settings so a store can be
paused, quarantined, or switched to provider-backed fetching without code
changes. Current Joom Browserless support becomes one provider implementation
behind `browser_provider`; it is not treated as source support unless the
adapter extracts a confident product.

Fetch result metadata:

- `strategy`
- `provider_name`
- `provider_request_id`
- `provider_cost_minor`
- `rendered`
- `http_status`
- `response_ms`
- `block_reason`
- `challenge_detected`
- `parser_version`
- `parser_confidence`

No provider response body, raw token, proxy URL, cookie, browser session, or
challenge token is persisted.

### Extraction Confidence

Adapters return confidence from `0.00` to `1.00`.

Product and price history update only when:

- `title` is non-empty;
- `price_minor` is positive;
- `currency` is known;
- confidence is at or above the source threshold;
- price is not ambiguous;
- adapter did not mark the response as blocked/challenged.

Low-confidence or ambiguous extraction records a failed attempt with a stable
reason and does not update the visible product card or price history.

Stable reasons include:

- `product_data_not_found`
- `low_confidence`
- `ambiguous_price`
- `captcha_detected`
- `proof_of_work_required`
- `provider_quota_exceeded`
- `provider_timeout`
- `provider_bad_response`
- `source_quarantined`

### Fetch Job Lifecycle

Extend `FetchJob` with:

- `status_reason`
- `started_at`
- `finished_at`
- `attempt_count`

Lifecycle:

- `queued`
- `running`
- `ok`
- `failed`
- `quarantined`
- `dead_letter`

Worker behavior:

- Set `running`, `started_at`, and increment/update attempt count when work
  begins.
- Set terminal status, `status_reason`, and `finished_at` on success or handled
  failure.
- On unexpected worker exception, record `dead_letter` and a safe error type,
  without raw response or secrets, then re-raise only when Celery retry policy
  requires it.

### Product Card And Price History

`GET /api/v1/products/{product_id}` returns product fields plus latest job and
latest attempt summary. The summary includes source, strategy/provider, reason,
block/challenge marker, parser version, confidence, and timestamps.

`GET /api/v1/products/{product_id}/price-chart` keeps the existing response
shape. If there are no points, it returns one empty/initial state payload:

- `points: []`
- `summary.lowest_price_minor: null`
- `summary.latest_price_minor: null`
- `currency: product.currency or null`

The WordPress renderer must not show two separate chart errors for the same
empty history state.

### Admin Diagnostics

Backend admin read endpoints expose:

- source status and policy summary;
- latest `FetchJob`;
- latest `FetchAttempt`;
- source domain;
- strategy and provider;
- reason and block/challenge marker;
- parser version and confidence;
- provider configured booleans and request/cost counters where available.

Admin responses never include provider tokens, proxy credentials, raw cookies,
raw sessions, challenge tokens, or raw marketplace bodies.

### Admin Settings

Add one global admin setting for the service request cadence:

- key: `price_refresh_interval_hours`;
- default: `8`;
- type: integer hours, minimum `1`;
- meaning: how often the service should request a fresh product price for
  active monitored items when no source-specific override is set.

The backend admin settings API exposes this value through
`GET/PATCH /api/v1/admin/settings`. New monitored sources use this global value
as their default fetch interval. Existing per-source `fetch_interval_hours`
values remain valid overrides so current source policy contracts and existing
admin edits are not broken. The scheduler and manual source-policy code resolve
the effective cadence as source override first, then
`price_refresh_interval_hours`.

## WordPress Architecture

The existing plugin flow stays intact:

- Account endpoint: `price-monitor`.
- Browser calls WordPress REST only:
  `/wp-json/cashback/v1/price-monitor/*`.
- WordPress signs backend HMAC requests through `Cashback_Price_Monitor_Client`.
- `Cashback_Price_Monitor_REST_Controller` checks backend source support before
  creating watchlist items.
- `Cashback_Price_Monitor_Account::hydrate_card()` uses backend product detail
  and price chart, then reuses `Cashback_Link_Checker_Service` for cashback
  activation.

Required UI changes are narrow:

- Map new backend codes `not_product_url`, `source_product_id_missing`, and
  `source_url_pattern_unsupported` to clear Russian copy.
- Keep `unsafe_url` visible as a clear URL-safety error instead of a generic
  fetch failure.
- Render one loading state while product data is not available.
- Render one initial chart state when price history is empty.
- Add one numeric admin field, `Частота обновления цены, часов`, to the existing
  Price Monitor settings form. It reads/writes backend
  `price_refresh_interval_hours`, defaults to `8`, validates a minimum of `1`,
  and is not exposed to account-page localized JS.
- Show diagnostics only where useful for admin; do not expose secrets in
  localized JS or HTML.

The plugin checkout has existing uncommitted changes in the admin surface. Any
implementation must inspect those files before editing and must not revert user
work.

## Deploy And Runtime Verification

Local gates before pushing `develop`:

```powershell
rtk py -m pytest -q
rtk ruff check .
rtk ruff format --check .
rtk mypy
rtk py -m pip check
rtk docker compose config --quiet
rtk git diff --check
```

Push only after local gates are green. Then verify GitHub Actions:

- `secret-scan`
- `quality`
- `deploy-test`

Read-only server checks after deploy:

- release SHA under `/home/igor/monitor_cashback/current`;
- `/health/live`;
- `/health/ready`;
- `docker compose ps`;
- API and worker logs tail without traceback/error/critical for the deployed
  smoke window.

Frontend smoke:

- create a temporary WordPress test user without logging the password;
- record user id and email;
- log in and open the account `price-monitor` endpoint;
- add one valid product URL for each required store;
- verify product card title, image, current price, optional rating, price chart,
  and loading/error state;
- try one invalid non-product URL for each required store and verify clear
  error copy;
- collect evidence with API statuses, screenshots without secrets, and server
  log summary;
- leave the user for repeat verification or provide the exact deletion command,
  according to the smoke result.

## Source Rollout Criteria

For each store, implementation is accepted only when local fake/fixture tests
prove:

- product URL accepted;
- non-product URL rejected with stable code;
- successful fetch updates product and writes one price point;
- low confidence or ambiguous price does not update product or price history;
- blocked/challenge response records a failed attempt with safe diagnostics;
- product detail and price chart API return the frontend contract.

Live frontend smoke is accepted only when the test server proves the same flow
through WordPress UI and backend worker. If a store hits anti-bot protection
after three source-specific attempts without a configured managed provider, stop
for that store and report the blocker without weakening the overall service.

## Store-Specific Starting Strategy

- Citilink: start with direct HTTP plus JSON-LD/meta/source parser fixtures.
- Wildberries: prefer stable structured public payload where safe, then direct
  HTML/provider fallback.
- Ozon: public product pages only; classify `403`/CAPTCHA as blocked; no
  cart/favorites/session capture.
- Yandex Market: prefer source-specific public structured data when stable;
  use provider fallback only with approved credentials.
- Joom: current Browserless-only path is not sufficient if proof-of-work blocks
  anonymous frontend API hydration; managed provider is expected.
- AliExpress: current live evidence indicates CAPTCHA; keep disabled until
  approved provider/API path is configured.

## Testing Strategy

Backend RED -> GREEN slices:

- URL classifier unit tests per source.
- Source service and watchlist contract tests for accepted/rejected URLs.
- Adapter fixture tests for extraction fields and confidence.
- Fetch pipeline tests for ladder order, metadata, low-confidence gating,
  price-history writes, and job lifecycle.
- Admin API contract tests for diagnostics, redaction, and the
  `price_refresh_interval_hours` default/update contract.
- Scheduler/source-policy tests for the effective refresh interval: per-source
  override first, then global default `8`.
- Worker tests for terminal job statuses and dead-letter behavior.

WordPress RED -> GREEN slices:

- REST controller tests for new backend error mappings.
- Account JS tests for one loading state, one empty chart state, and invalid URL
  copy.
- Admin tests for displaying, validating, and saving the
  `price_refresh_interval_hours` field with default `8`.
- Admin tests for diagnostics display/redaction if backend diagnostics are
  surfaced in the plugin.

Runtime verification:

- local gates;
- GitHub Actions gates;
- read-only server health/log checks;
- frontend browser smoke.

## Open Risks

- Joom and AliExpress are unlikely to become fully monitorable without managed
  provider access.
- Ozon and Yandex Market may require managed provider or official public data
  access depending on live responses.
- Provider pricing, availability, and allowed use are time-sensitive and must be
  rechecked before purchase or activation.
- Existing smoke evidence proves Citilink direct fetch can work, but it does not
  prove all required stores work.

These risks do not block local architecture work. They do block claiming the
full goal complete until current live frontend/server evidence proves every
required store or the user supplies the required provider/access decision.
