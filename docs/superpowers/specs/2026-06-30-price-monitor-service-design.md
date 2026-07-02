# Price Monitor Service Design

Date: 2026-06-30
Status: Approved design sections 1-3
Repos:
- Backend service: `F:\cash-back\monitor_cashback`
- WordPress plugin: `F:\wamp64\www\kash-back\wp-content\plugins\cash-back`

## Goal

Build a production-ready price monitoring service where a WordPress user can add a
product URL, see a product card with current product data and price history, set a
desired price, receive email alerts, and use the existing cashback activation
flow when the store is connected to the cashback catalog.

The service must be implemented with RED -> GREEN TDD, separate branches,
security checks, commits, pushes, deployment to the test server, and server-side
verification.

## Current State

The backend repo is already the standalone FastAPI service root. It owns the
price-monitor domain and currently provides a foundation:

- FastAPI health and watchlist APIs.
- HMAC verification for WordPress-facing mutations.
- URL canonicalization and fail-closed URL safety checks.
- SQLAlchemy models for products, watchlist items, price points, source status,
  idempotency, outbox/inbox, and fetch jobs.
- RabbitMQ/Celery worker scaffolding.
- CI and develop-only test deployment workflow.

The WordPress plugin already provides reusable cashback surfaces:

- `cashback/v1/link-checker/check` and `/activate` with REST nonce and rate
  limiting.
- `Savello_Cashback_Internal_REST_Controller` under `savello-internal/v1`.
- Internal HMAC settings and auth for server-to-server calls.
- Existing direct-link cashback resolution and activation-page URL generation.

The missing work is the production feature layer: supported store management,
fetch execution, proxy policy, product card data, alerting, retention, WordPress
admin/account UI, and end-to-end deployment verification.

## Research Summary

Commercial reference services such as Keepa, CamelCamelCamel, PriceSpy, and
PriceRunner converge on the same product shape: watchlists, price history, price
drop alerts, supported-store/product matching, and compact product cards.

Open-source/reference tooling informs the implementation:

- changedetection.io is useful as a self-hosted watch/notification reference,
  but it is a generic page-change watcher rather than a domain-owned product
  price service.
- Crawlee for Python supports HTTP and Playwright crawlers, session pools, and
  tiered proxy URLs, which maps well to a staged fetch pipeline.
- Playwright Python supports proxy configuration at browser-launch and browser
  context level, which fits per-source browser fallback isolation.

References:
- https://keepa.com/
- https://camelcamelcamel.com/
- https://pricespy.co.uk/
- https://www.pricerunner.com/
- https://github.com/dgtlmoon/changedetection.io
- https://crawlee.dev/python/docs/guides/proxy-management
- https://playwright.dev/python/docs/network

## Approaches Considered

Recommended: production vertical slice.

This delivers the full user workflow for supported stores: admin store setup,
user add/list/edit/delete, deduplication, current product data, history chart,
desired-price alerts, cashback/direct purchase action, tests, deployment, and
server smoke checks. It keeps the scope end-to-end while avoiding overbuilding
unsupported stores.

Alternative: full multi-store/browser-heavy release immediately.

This tries to solve every anti-bot/store variant up front. It is higher risk
because each real marketplace needs independent fetch reliability evidence,
proxy tuning, and legal posture review.

Alternative: backend-only first.

This is simpler for API delivery but fails the requested end state because the
WordPress admin and user account flows would still be missing.

## Architecture

The backend remains the owner of monitoring data:

- supported stores
- products
- watchlist items
- fetch jobs and fetch attempts
- price points
- alert state
- retention policy
- source health and diagnostics

WordPress remains the owner of:

- admin and account UI
- WordPress users and capabilities
- REST nonce/cookie auth for browser requests
- email delivery
- cashback UI and activation UX
- proxy signing to the backend

Communication boundaries:

1. Browser talks only to WordPress REST endpoints.
2. WordPress signs backend requests with the existing backend HMAC contract.
3. Backend optionally calls WordPress internal APIs for merchant/cashback/user
   limit data using the existing `savello-internal/v1` HMAC model.
4. Backend never exposes internal service secrets or raw partner credentials to
   the browser.

## Data Model

Add or extend backend entities:

- `monitored_sources`
  - domain, display name, logo URL, status, fetch interval hours, history
    retention days, browser fallback flag, proxy policy, created/updated audit
    timestamps.
- `proxy_pools`
  - name, status, tier ordering, source scope, notes.
- `proxy_endpoints`
  - pool, tier, URL/secret reference, status, last success/failure metadata.
    Raw proxy credentials must be stored as deployment secrets or encrypted
    fields, not logged.
- `products`
  - canonical URL, URL hash, source, title, image URL, rating, current price,
    currency, last fetch status, last fetched timestamp.
- `watchlist_items`
  - owner external user id, product, target price, currency, status, created,
    updated, deleted. Active duplicates for the same user and product are
    rejected; deleted rows allow re-add.
- `price_points`
  - product, observed price, currency, source, observed timestamp, fetch attempt.
- `fetch_jobs`
  - product, source, scheduled time, priority, status, retry state.
- `fetch_attempts`
  - job, strategy, proxy tier, HTTP status/error class, response time,
    product-data-found flags, redacted diagnostic reason.
- `alert_events`
  - watchlist item, target price, observed price, dedup key, status, sent time,
    provider response metadata.

Retention:

- Product and price history remain for up to 90 days after the last active
  watchlist item is deleted unless a source-specific policy sets a shorter
  period.
- Active tracked products keep history according to the source retention policy.

## User Flow

1. User opens the WordPress account price-monitor page.
2. User submits a product URL and optional desired price.
3. WordPress validates nonce and rate limits the request.
4. WordPress asks the backend whether the URL domain is supported.
5. If unsupported, WordPress returns `unsupported_store` and the UI shows
   "Магазин не поддерживается".
6. If supported, WordPress creates or reactivates the backend watchlist item.
7. Backend canonicalizes the URL, reuses an existing product when the canonical
   product already exists, records an outbox event, and schedules an immediate
   fetch job.
8. WordPress uses the existing cashback link-checker/internal API path to decide
   whether to show "Активировать кэшбэк" or the direct "Купить" action in the UI.
9. The account page renders the product card. If the first fetch is still
   pending, the card shows a pending state and polls or refreshes through the
   WordPress proxy.
10. When price data is fetched, the card shows image, title, price, rating,
    source name/logo, small price chart, and the correct action button.
11. The card menu supports editing desired price and deleting the watch.
12. Delete marks the watchlist item deleted and leaves product/history for the
    retention window.

## Admin Flow

WordPress admin gets a price-monitor settings area under the existing cashback
admin parent. It manages:

- backend base URL and backend HMAC secret/status;
- WordPress internal API enablement/secret status;
- supported stores: domain, display name, logo, default fetch interval hours,
  retention days, status, browser fallback allowed;
- global max tracked products per user, default 10;
- proxy pools and source-to-pool assignment;
- read-only diagnostics for source health and recent fetch failures.

Admin saves must use capability checks, nonces, sanitization, escaping, and
redacted secret display. WordPress stores UI-facing settings; backend stores
monitoring execution state.

## Fetch And Proxy Strategy

The fetch pipeline is staged from cheapest to most expensive:

1. Direct HTTP fetch with redirect safety checks.
2. HTTP fetch through free/internal proxy tier when configured.
3. HTTP fetch through low-cost datacenter proxies.
4. HTTP fetch through higher-cost residential/mobile proxies.
5. Browser rendering through a thin Playwright/Crawlee adapter for sources that
   explicitly allow browser fallback.

Every redirect is revalidated against SSRF and supported-source policy before
the next request. Fetchers first try structured data such as JSON-LD/schema.org,
OpenGraph, and common product meta tags. Source-specific selectors are allowed
only inside source adapters or source configuration, not scattered through API
handlers.

Proxy rotation rules:

- Prefer the lowest healthy tier.
- Retire or cool down proxies that repeatedly fail with block, timeout, or
  invalid product-data classifications.
- Store only redacted proxy information in attempts and logs.
- Keep browser fallback feature-gated and tested with fakes before using real
  browser dependencies in production.

## API Contracts

Backend endpoints to add or extend:

- `GET /api/v1/sources/supported?url=...`
- `GET /api/v1/watchlist/items`
- `POST /api/v1/watchlist/items`
- `PATCH /api/v1/watchlist/items/{item_id}`
- `DELETE /api/v1/watchlist/items/{item_id}`
- `GET /api/v1/products/{product_id}`
- `GET /api/v1/products/{product_id}/price-history`
- `GET /api/v1/products/{product_id}/price-chart`
- admin endpoints for monitored sources, proxy pools, source health, and fetch
  diagnostics.

WordPress endpoints to add:

- account REST proxy for add/list/edit/delete/refresh product watches;
- admin REST/AJAX or Settings API endpoints for monitor settings and source
  management;
- activation endpoint reuse through existing link-checker endpoints instead of
  copying CPA-network logic.

All mutating backend endpoints require HMAC and idempotency. Browser-facing
WordPress endpoints require REST nonce and the appropriate capability or logged
in user.

## Error Handling

Use stable machine codes and short Russian UI messages:

- `unsupported_store` -> "Магазин не поддерживается"
- `duplicate_watchlist_item` -> "Товар уже отслеживается"
- `limit_exceeded` -> "Достигнут лимит отслеживаемых товаров"
- `fetch_pending` -> "Данные товара загружаются"
- `fetch_failed` -> "Не удалось обновить данные товара"
- `cashback_unavailable` -> "Кэшбэк не начислится"
- `invalid_target_price` -> "Проверьте желаемую цену"

Admin diagnostics include redacted strategy, proxy tier, error type, response
status, and timestamp. They must not expose secrets, raw cookies, or raw browser
sessions.

## Notifications

The backend decides when a tracked item crosses the desired price threshold and
records an alert event with dedup/cooldown protection. WordPress sends the email
using its existing mail stack through an internal HMAC endpoint. The alert
payload includes only the user id, product card summary, observed price, target
price, product URL, and cashback/direct action metadata required for email
rendering.

Notification constraints:

- no duplicate email for the same threshold crossing within the cooldown window;
- per-user daily limit from WordPress/internal user limits;
- failed dispatches retry with bounded backoff;
- successful events are auditable without storing unnecessary personal data.

## Security And Privacy

The service keeps the existing security boundary:

- no marketplace passwords;
- no raw cookies;
- no raw browser session captures;
- source-specific public product fetching may use managed unblocker APIs,
  browser rendering, proxy rotation, and challenge-aware adapters when approved
  for the monitored source;
- no browser-side exposure of backend or partner secrets;
- fail-closed URL and redirect validation;
- HMAC on server-to-server calls;
- idempotency for mutations;
- owner scoping for all user data;
- capability/nonces for WordPress admin and account requests;
- prepared statements or ORM-bound parameters for database work;
- redacted logs and diagnostics.

The browser fallback may render public product pages only for configured
supported sources. Any official marketplace OAuth, cart monitoring, favorites
import, or authenticated marketplace flow is outside this spec unless separately
approved with a legal/security design.

## Testing Strategy

Backend RED -> GREEN tests:

- URL source allowlist and unsupported-store rejection.
- Watchlist create, duplicate active item rejection, deleted item re-add.
- Per-user max tracked product limit.
- Product reuse across users.
- Product detail/card response contract.
- Price history and chart response contract.
- Fetch scheduler interval behavior.
- Fetch pipeline strategy ordering and proxy tier fallback using fakes.
- Fetch attempt diagnostics redaction.
- Desired-price alert evaluation, cooldown, daily limit, and dispatch outbox.
- HMAC/idempotency and owner scoping.
- Migration smoke test.

WordPress RED -> GREEN tests:

- admin settings registration, capability checks, nonce checks, sanitization,
  escaping, and secret redaction;
- account endpoint rendering and asset enqueueing;
- REST proxy signing to backend;
- add/list/edit/delete UI behavior;
- cashback action reuse through existing link-checker/internal service;
- JS tests for card rendering, duplicate/limit/unsupported errors, menu actions,
  and activation button behavior.

Verification gates:

- backend: `rtk python -m pytest`, `rtk python -m ruff check .`,
  `rtk python -m ruff format --check .`, `rtk python -m mypy`,
  `rtk docker compose config --quiet`, migration smoke;
- WordPress: targeted PHPUnit, `rtk php -l` for changed PHP files, targeted
  PHPCS, node tests, and `rtk git diff --check`;
- security: secret scan, dependency/audit gate, review of auth and SSRF paths.

## Branching, Commit, Push, Deploy

Backend work starts from a new branch off `develop`. WordPress work starts from
a new branch off the plugin's `main` branch. The backend test deploy remains
develop-driven, so implementation will merge or push according to the repo's
existing deployment policy after the feature branch passes review gates.

Deployment verification must prove:

1. migrations applied on the test server;
2. service health endpoints pass;
3. admin can add a supported source;
4. unsupported store URL fails with the expected error;
5. supported product URL creates a watchlist item;
6. duplicate active item is rejected;
7. limit is enforced;
8. fetch creates product card data and a price point;
9. price chart returns data;
10. desired-price alert can be evaluated and dispatched through WordPress test
    mail path;
11. delete removes the user's active watch but retains product/history for
    retention.

## Implementation Decomposition

The implementation plan should split work into separately testable slices:

1. Backend source allowlist and admin source API.
2. Backend watchlist limit, duplicate semantics, and deleted-item re-add.
3. Product card/detail and chart contract.
4. Fetch pipeline execution with fake HTTP/proxy/browser adapters.
5. Alert evaluation and WordPress email dispatch integration.
6. WordPress backend-client/proxy layer.
7. WordPress admin settings/source UI.
8. WordPress account UI and card interactions.
9. End-to-end deployment and server smoke.

Each slice must start with tests that fail for the expected reason, then move to
the smallest implementation that makes the tests green.

## Non-Goals

- No raw marketplace login/cookie/session capture.
- Managed unblocker, browser rendering, proxy rotation, and challenge-aware
  adapters are allowed for approved public product-page sources when they keep
  rate limits, cost accounting, diagnostics, and secret redaction.
- No cart/favorites monitoring without official OAuth or separate approved
  legal/security design.
- No broad rewrite of existing cashback activation logic.
- No public direct browser access to backend internals.
- No production rollout from `master` until the repo's production deployment
  policy exists.

## Approval

The user approved design sections 1-3 in the Codex thread before this document
was written. This spec expands those approved sections into an implementation
contract and must be reviewed by the user before writing the implementation
plan.
