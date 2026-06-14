# Monitor Cashback Price Assistant Specification

**Status:** Product and technical specification for planned work  
**Date:** 2026-06-14  
**Repository:** `F:\cash-back\monitor_cashback`  
**Primary artifact:** planning document only; no implementation is included

## 1. Product Vision

Monitor Cashback Price Assistant is a cashback-aware price assistant for Savello Club users. It combines price tracking, price history, target-price alerts, and effective-price calculation after cashback.

The MVP focuses on a safe, narrow user flow: a logged-in WordPress user manually adds product links in the personal account, WordPress proxies the request to the existing FastAPI price-monitor backend, and the user sees tracked product cards, price history, cashback status, and a cashback deeplink when available.

The product should move toward the target model represented by YoloPrice, Cheaper, and Palert:

- YoloPrice-style cart and favorites monitoring for Ozon, Wildberries, and Yandex Market, price drop alerts, and cross-store comparison.
- Cheaper-style real-time comparison across marketplaces and major stores controlled by the product/admin team.
- Palert-style link/SKU/name tracking, price history, extension overlay, target alerts, Telegram/browser/email notifications, analytics, and API-like scenarios.

### Non-goals

- Do not store marketplace passwords, marketplace cookies, auth cookies, refresh tokens, or private marketplace account credentials on the server.
- Do not automate unauthorized marketplace account access.
- Do not implement captcha bypass or forbidden access mechanisms.
- Do not build WordPress REST API, browser extension code, marketplace adapters, migrations, or tests as part of this specification task.

## 2. Current State vs Target Model

### Current FastAPI backend foundation

The `price-monitor/backend` service already has:

- HMAC-protected incoming requests from WordPress/FastAPI clients.
- Watchlist CRUD endpoints and a read-optimized watchlist UI endpoint.
- Price history and price chart endpoints.
- Product card response models with local cashback snapshot data.
- Cashback deeplink generation through the internal cashback API client.
- Fetch jobs, Celery beat scheduling, multi-stage fetch executor, source health, source quarantine/cooldown, proxy pool/cost controls, fetch attempts, cleanup tasks, and Prometheus metrics.
- Internal FastAPI admin diagnostics for overview, sources, products, jobs, errors, fetch economics, proxy pools, source health, and fetch attempts.
- Demo/test URL normalizer support only for `testshop.local`, `example-market.local`, and `demo-store.local`.

### Missing for the target product

- No WordPress user-facing proxy endpoints for Price Assistant yet.
- No WordPress personal-account UI for watchlist cards, chart, manual add/edit/delete, or import.
- No real Ozon/Wildberries/Yandex Market URL normalizers, parsers, or source extraction schemas.
- No browser extension import of cart/favorites/product-page data into Price Assistant.
- No cross-store comparison or product matching.
- No user-facing notification delivery surface for price alerts.
- No tariffs UI or paid-feature management in the Price Assistant surface.

### Target phases

1. **Phase 1:** WordPress proxy + personal account + manual link tracking.
2. **Phase 2:** Browser extension import of carts/favorites from Ozon, Wildberries, and Yandex Market.
3. **Phase 3:** Price comparison across admin-managed stores.
4. **Phase 4:** Improved matching, notifications, tariffs, and analytics.

## 3. MVP User Scenarios

### User: add a product manually

1. User opens the Savello Club personal account.
2. User opens the Price Assistant tab.
3. User pastes a product URL and optionally sets:
   - target product price;
   - target effective price after cashback.
4. WordPress validates the user session and sends the request to FastAPI with server-side HMAC.
5. FastAPI normalizes the URL against the supported source allowlist.
6. If the product is accepted, the user sees a tracked item card.
7. If the source is unsupported, the UI shows a deterministic error and no partial product is created.

### User: manage tracked products

1. User views tracked product cards with title, source, image, current price, availability, cashback status, and optional chart summary.
2. User opens a full price chart for a product.
3. User changes target price or target effective price.
4. User pauses or deletes tracking; backend performs soft delete/deactivation.
5. User opens the cashback deeplink when cashback is available.

### User: import links manually

1. User uploads CSV/JSON or pastes multiple links.
2. WordPress validates file type, size, row count, and basic shape before proxying.
3. Each row is processed independently.
4. Valid rows are added or reported as already tracked.
5. Invalid rows return per-row errors; one bad row must not make the whole import unsafe.

### User: extension import in Phase 2

1. User explicitly enables Price Assistant import in the browser extension.
2. The extension content script runs only on supported marketplace domains and only with least-privilege host permissions.
3. The content script extracts visible product data from cart, favorites, or product page DOM.
4. The extension sends product URLs and minimal metadata to WordPress.
5. The extension must not send marketplace cookies, passwords, auth tokens, local storage secrets, or private account credentials.

## 4. Admin Scenarios

### MVP admin operations

- View FastAPI admin overview, source status, product list, fetch jobs, recent errors, fetch economics, source health, proxy pools, and fetch attempts.
- Enable or disable a source.
- Review fetch failures and source quarantine/cooldown state.
- Inspect proxy pool health and cost without exposing proxy endpoint secrets.
- Control which stores/sources are eligible for user-facing tracking.

### Later admin operations

- Manage comparable stores for Phase 3.
- Configure source profiles, difficulty classes, fallback policy, and fetch cost constraints.
- Review matching confidence and approve/disable weak product matches.
- Configure tariffs, limits, notification channels, and analytics dashboards.
- Review abuse, overcollection, failed imports, and high-cost source behavior.

## 5. Privacy And Security Requirements

### Credential and cookie boundaries

- The server must never store marketplace passwords, marketplace session cookies, auth cookies, refresh tokens, or private marketplace credentials.
- WordPress may authenticate the Savello user with its existing user session, but marketplace account authentication remains outside the server.
- Browser extension collection must be consent-based and limited to visible page/cart/favorites product data.
- Server-side marketplace account login, cookie replay, or password-based import is prohibited.

### Trust boundaries

- WordPress remains the user-auth boundary.
- FastAPI remains an internal HMAC-protected backend.
- Browser extension talks to WordPress public/proxy endpoints, not directly to internal FastAPI.
- FastAPI admin endpoints remain internal/admin-only behind `ADMIN_API_KEY`.

### Fail-closed behavior

- Unsupported sources fail closed.
- Missing/invalid HMAC fails closed.
- `site_id` mismatch fails closed.
- Disabled source, active quarantine, or cooldown blocks fetch escalation.
- Unavailable cashback limits must not silently grant premium limits.
- Tests must not make real marketplace HTTP requests or real cashback internal API requests.

### Logging and metrics

- Logs and metrics must not expose PII, HMAC secrets, API keys, proxy endpoint refs, cookies, passwords, marketplace account data, or raw imported private page content.
- Proxy labels and admin responses must keep `endpoint_ref` and userinfo/password parts hidden.

## 6. API Contracts

### Existing WordPress/FastAPI HMAC contract

FastAPI already expects:

- `X-Savello-Site`
- `X-Savello-Timestamp`
- `X-Savello-Signature`

Signature:

```text
hmac_sha256(timestamp + "." + raw_body, PRICE_MONITOR_INCOMING_SECRET)
```

The request `site_id` must match `X-Savello-Site`.

### Existing FastAPI endpoints to reuse

#### `POST /v1/watchlist/items`

Purpose: add a product to a user's watchlist.

Request body:

```json
{
  "site_id": "savelloclub.ru",
  "external_user_id": "wp:123",
  "product_url": "https://example-market.local/item/abc-777",
  "target_price": "10000.00",
  "target_effective_price": "9500.00",
  "region_code": "default"
}
```

Response:

```json
{
  "subscription_id": 1,
  "tracked_product_id": 10,
  "site_id": "savelloclub.ru",
  "external_user_id": "wp:123",
  "product_url": "https://example-market.local/item/abc-777",
  "source": "example_market",
  "external_product_id": "abc-777",
  "region_code": "default",
  "target_price": "10000.00",
  "target_effective_price": "9500.00",
  "is_active": true,
  "result": "created"
}
```

Known errors:

- `400` for unsupported URL source.
- `403` for site/header mismatch.
- `422` for `max_tracked_products_exceeded`.

#### `GET /v1/watchlist/ui`

Purpose: fetch read-optimized card data for WordPress UI.

Query:

- `site_id`
- `external_user_id`
- `include_chart_summary=true|false`
- `limit=1..100`
- `offset>=0`

Response shape:

```json
{
  "items": [
    {
      "subscription_id": 1,
      "tracked_product_id": 10,
      "title": "Product title",
      "source_display_name": "Ozon",
      "image_url": "https://cdn.example/product.jpg",
      "current_price": "10000.00",
      "currency": "RUB",
      "availability": true,
      "cashback": {
        "cashback_status": "partner_estimated",
        "cashback_available": true,
        "display_policy": "show_exact_rate"
      },
      "chart_summary": {
        "trend": "near_average",
        "delta_vs_avg_percent": "0.00",
        "headline": "Price is near average"
      }
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1,
    "has_more": false
  }
}
```

#### `GET /v1/products/{tracked_product_id}/price-chart`

Purpose: fetch chart data for a product owned by the current user.

Query:

- `site_id`
- `external_user_id`
- `days=1..90`
- `granularity=raw|daily`
- optional `currency`

Response shape:

```json
{
  "tracked_product_id": 10,
  "title": "Product title",
  "currency": "RUB",
  "summary": {
    "current_price": "10000.00",
    "avg_price": "10500.00",
    "min_price": "9900.00",
    "max_price": "12000.00",
    "delta_vs_avg_percent": "-4.76",
    "trend": "below_usual"
  },
  "series": [
    {"ts": "2026-06-14T10:00:00Z", "price": "10000.00"}
  ],
  "y_axis": {
    "min": "9900.00",
    "avg": "10500.00",
    "max": "12000.00"
  },
  "labels": {
    "headline": "Below usual price"
  }
}
```

#### `PATCH /v1/watchlist/items/{subscription_id}`

Purpose: update target prices or active state.

Query:

- `site_id`
- `external_user_id`

Request body:

```json
{
  "target_price": "9000.00",
  "target_effective_price": "8500.00",
  "is_active": true
}
```

#### `DELETE /v1/watchlist/items/{subscription_id}`

Purpose: soft-delete/deactivate a watchlist item.

Query:

- `site_id`
- `external_user_id`

#### `POST /v1/watchlist/items/{subscription_id}/cashback-link`

Purpose: create or return a cashback deeplink for a tracked product.

Request body:

```json
{
  "site_id": "savelloclub.ru",
  "external_user_id": "wp:123"
}
```

Known errors:

- `404` if the subscription is not active or does not belong to the user.
- `422` if cashback is unavailable for the product.
- `503` if the cashback API is unavailable.

### Planned WordPress public/proxy facade

These endpoints are not implemented by this specification. They are the intended Phase 1 contract for later agents.

#### `GET /wp-json/cashback/v1/price-assistant/watchlist`

Authentication: WordPress logged-in user session.

Behavior:

- Resolve current WordPress user to `external_user_id`.
- Sign and proxy to FastAPI `GET /v1/watchlist/ui`.
- Return only the current user's items.

#### `POST /wp-json/cashback/v1/price-assistant/watchlist`

Authentication: WordPress logged-in user session and nonce.

Request body:

```json
{
  "product_url": "https://market.example/product/123",
  "target_price": "10000.00",
  "target_effective_price": "9500.00",
  "region_code": "default"
}
```

Behavior:

- Validate URL as a URL string, but source allowlist is ultimately enforced by FastAPI.
- Add `site_id` and `external_user_id` server-side.
- Sign and proxy to FastAPI `POST /v1/watchlist/items`.

#### `PATCH /wp-json/cashback/v1/price-assistant/watchlist/{id}`

Authentication: WordPress logged-in user session and nonce.

Request body:

```json
{
  "target_price": "9000.00",
  "target_effective_price": "8500.00",
  "is_active": true
}
```

Behavior:

- Add `site_id` and `external_user_id` server-side.
- Proxy to FastAPI `PATCH /v1/watchlist/items/{subscription_id}`.

#### `DELETE /wp-json/cashback/v1/price-assistant/watchlist/{id}`

Authentication: WordPress logged-in user session and nonce.

Behavior:

- Add `site_id` and `external_user_id` server-side.
- Proxy to FastAPI `DELETE /v1/watchlist/items/{subscription_id}`.

#### `POST /wp-json/cashback/v1/price-assistant/import`

Authentication: WordPress logged-in user session and nonce or extension-authenticated WordPress cookie flow.

Request body:

```json
{
  "source": "ozon",
  "import_type": "cart",
  "consent_version": "price-assistant-import-v1",
  "collected_at": "2026-06-14T10:00:00Z",
  "items": [
    {
      "product_url": "https://www.ozon.ru/product/123",
      "title": "Visible product title",
      "price": "10000.00",
      "currency": "RUB",
      "quantity": 1
    }
  ]
}
```

Rules:

- `import_type` values: `cart`, `favorites`, `product_page`, `manual_file`.
- `items[]` must not include cookies, passwords, auth tokens, local storage values, or raw private account data.
- The endpoint must validate row count, payload size, source allowlist, URL shape, and consent metadata.
- Each item should be processed independently with per-item status.

### Planned extension to WordPress contract

The extension must call only the WordPress proxy import endpoint:

```text
POST /wp-json/cashback/v1/price-assistant/import
```

Required payload fields:

- `source`
- `import_type`
- `items[]`
- `consent_version`
- `collected_at`

Prohibited payload fields:

- marketplace cookies;
- WordPress auth cookies;
- passwords;
- auth tokens;
- refresh tokens;
- marketplace local storage/session storage secrets;
- full HTML snapshots containing private account data.

### FastAPI admin contract

Existing `/admin/*` endpoints remain internal/admin-only and protected by `ADMIN_API_KEY`. They are diagnostics and operations support, not public product APIs.

## 7. Phased Roadmap

### Phase 1: WordPress proxy + personal account + manual links

Deliverables:

- WordPress Price Assistant proxy endpoints.
- Personal-account Price Assistant tab.
- Manual add/list/update/delete product tracking.
- Price chart display using FastAPI chart data.
- Cashback deeplink button.
- CSV/JSON/manual multi-link import fallback.
- User-facing empty, loading, validation, limit, unsupported-source, and unavailable-state handling.

Acceptance criteria:

- Logged-in user can manage only their own tracked products.
- WordPress signs all FastAPI calls server-side.
- FastAPI remains unreachable from browser clients in the product flow.
- Unsupported sources fail closed.
- No real marketplace HTTP requests are made by WordPress tests.

### Phase 2: Browser extension import for carts/favorites

Deliverables:

- Consent UI in extension for Price Assistant import.
- Content scripts for supported domains: Ozon, Wildberries, Yandex Market.
- Import modes: cart, favorites, product page.
- Minimal visible product payload sent to WordPress import endpoint.
- No server-side marketplace account access.

Acceptance criteria:

- Extension never sends marketplace cookies/passwords/auth tokens.
- User can review imported items before or during submission.
- Tests use static DOM fixtures and fake network.
- Permission scope is limited to supported marketplace domains.

### Phase 3: Admin-managed store comparison

Deliverables:

- Admin-managed comparable store/source list.
- Source profile controls for comparison-eligible stores.
- Comparison result model for same or similar products.
- Controlled fetch strategy per source, with cost budget and quarantine respected.
- UI/API surface that can show alternative offers where matching confidence is acceptable.

Acceptance criteria:

- Admin controls which stores participate.
- Matching is never presented as exact when confidence is low.
- High-cost source behavior is gated by policy.
- No arbitrary scraping expansion outside configured sources.

### Phase 4: Improved matching, notifications, tariffs, analytics

Deliverables:

- Matching confidence model and admin review workflow.
- Target price and effective price notifications.
- Notification channels: email first, then browser push/Telegram if approved.
- Tariff/limit management for tracked product count, history window, manual refresh, browser fallback, alert volume.
- Product, source, fetch cost, and conversion analytics dashboards.
- Optional analytics/export API for approved internal or B2B scenarios.

Acceptance criteria:

- Notifications are rate-limited and deduplicated.
- Tariff limits fail closed.
- Analytics exclude secrets and unnecessary PII.
- Matching quality is measurable and reviewable.

## 8. Threat Model

| Threat | Risk | Mitigation |
| --- | --- | --- |
| Auth bypass between WordPress and FastAPI | Cross-user or anonymous access to watchlist data | WordPress user session boundary, FastAPI HMAC, `site_id` header/body match, current-user `external_user_id` generated server-side |
| HMAC replay | Reuse of signed requests | Timestamp skew limit, raw-body signing, `hmac.compare_digest`; future idempotency keys for mutating proxy calls |
| IDOR across users | User reads or modifies another user's subscriptions | FastAPI queries scoped by `site_id + external_user_id`; WP must never accept client-provided `external_user_id` |
| SSRF through arbitrary URLs | Backend fetches internal/private resources | Source allowlist, URL normalizer, no arbitrary URL fetch, unsupported source rejection |
| Stored marketplace credentials | Privacy/security breach | Server never stores marketplace credentials/cookies/tokens; extension sends visible product data only |
| Extension overcollection | User privacy harm | Explicit consent, least-privilege host permissions, DOM fixture tests proving prohibited fields are absent |
| Poisoned import payload | XSS, CSV injection, invalid product records | Schema validation, output escaping, CSV cell hardening, per-row errors, size limits |
| Proxy secret leaks | Provider credential exposure | Do not serialize `endpoint_ref`, proxy userinfo, API keys, or secrets in admin/API/metrics/logs |
| Abusive fetch loops | Source bans and cost spikes | Scheduler limits, source health, cooldown, quarantine, proxy cost budget, duplicate queued/running guard |
| Captcha pressure | Forbidden escalation or operational instability | No captcha bypass; captcha-like events quarantine source and stop escalation |
| PII leakage in logs | Compliance and privacy risk | Structured redacted logging, safe metrics labels, no raw private import snapshots |

## 9. Test Strategy For Future Implementation

This specification does not add tests. Future implementation prompts must follow TDD and keep all external HTTP mocked/faked.

### WordPress tests

- Logged-in user can list/add/update/delete only their own watchlist items.
- Anonymous user is rejected.
- Nonce/auth validation works for mutating endpoints.
- WordPress signs FastAPI requests with correct HMAC.
- Client-provided `site_id` or `external_user_id` is ignored/rejected.
- Invalid URL, unsupported source, FastAPI `422`, FastAPI `503`, and timeout responses are handled safely.
- CSV/JSON import validates file size, row count, required fields, and per-row errors.

### FastAPI tests

- Source allowlist rejects unknown real-world or internal URLs.
- HMAC missing/expired/invalid requests fail.
- Import contract validation rejects prohibited fields.
- No external marketplace HTTP occurs in tests.
- Cashback internal API calls are mocked/faked.
- Scheduler respects freshness, cost budget, source health, quarantine, and duplicate jobs.
- Proxy/cost/admin responses do not serialize secrets.

### Extension tests

- Consent gate blocks import until explicitly enabled.
- DOM extraction works from static fixtures for cart, favorites, and product page.
- Payload never contains cookies, passwords, auth tokens, local/session storage secrets, or full private HTML.
- Host permissions are limited to supported marketplace domains.
- Network calls are fake/mocked.

### Contract and security tests

- WordPress proxy payloads match FastAPI schemas.
- Replay/expired signature scenarios fail.
- Cross-user access attempts fail.
- SSRF-like URLs fail closed.
- Logs and metrics redact secrets.

## 10. Implementation Prompts For Next Agents

1. **Phase 1 proxy only:** Create Phase 1 WordPress price-assistant proxy endpoints and tests only; no UI yet; all FastAPI calls mocked in PHPUnit.
2. **Phase 1 personal account UI:** Create Phase 1 personal account UI consuming WP proxy; manual add/list/edit/delete and chart rendering; no marketplace requests.
3. **Manual import fallback:** Add CSV/JSON manual import fallback through WordPress proxy; validate rows; no extension code.
4. **Marketplace URL normalizers:** Add real marketplace URL normalizers for Ozon/WB/YandexMarket in FastAPI; tests only with static URLs; no fetching.
5. **Extension import:** Add extension consent plus content-script import for visible cart/favorites data; send only URLs/metadata to WordPress; no cookies/passwords.
6. **Admin comparison sources:** Add admin-managed comparison sources and store profiles; no automatic matching yet.
7. **Comparison matching MVP:** Add cross-store comparison/matching MVP with confidence score and admin review tools.
8. **Notifications/tariffs/analytics:** Add notifications, tariffs, and analytics in separate scoped prompts after Phase 3 is green.

## 11. Explicitly Not Implemented In This Spec Task

- No code changes.
- No migrations.
- No WordPress REST API implementation.
- No WordPress personal-account UI.
- No browser extension code.
- No marketplace adapters, parsers, or real source support.
- No real marketplace HTTP requests.
- No real cashback internal API requests in tests.
- No tests added.
- No captcha bypass or prohibited access mechanisms.
- No public API behavior changes.

## 12. Source References

- YoloPrice: https://yoloprice.com/
- YoloPrice Google Play listing: https://play.google.com/store/apps/details?id=com.yolo_price_mobile
- Cheaper: https://cheaper.ru/
- Cheaper Google Play listing: https://play.google.com/store/apps/details?id=ru.cheaper
- Palert: https://palert.io/
- Palert Russian site: https://palert.ru/
- Palert Firefox extension listing: https://addons.mozilla.org/firefox/addon/palert-price-tracker/
