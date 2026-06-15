# Session Connector Architecture

## Purpose

This document describes safe ways to connect marketplace carts and favorites to
the Price Assistant when marketplaces do not provide official OAuth.

It is an architecture document only. It does not add code, database migrations,
WordPress REST API routes, browser extension code, mobile application code,
marketplace adapters, captcha bypass logic, or real marketplace requests.

The MVP recommendation is to use only device-local modes:

- Device-Local Browser Extension Mode.
- Device-Local Mobile WebView Mode.

High-Risk Remote Session Mode is documented only as a rejected/deferred option
under the current `spec.md`. It is not allowed for MVP implementation.

## Trust Boundaries

- Marketplace authentication stays on the user's device.
- WordPress remains the user-authenticated public/proxy boundary.
- FastAPI remains the internal HMAC-protected backend.
- The backend receives only a sanitized item list.
- Marketplace passwords, marketplace cookies, auth cookies, refresh tokens,
  local storage secrets, session storage secrets, and full private HTML snapshots
  must never be sent to WordPress or FastAPI in device-local modes.

The intended flow is:

```text
User device -> WordPress proxy -> FastAPI internal API
```

The browser or mobile app must not call the internal FastAPI service directly in
the product flow. WordPress adds `site_id`, resolves the current WordPress user,
and signs upstream requests with the existing HMAC contract.

## Mode 1: Device-Local Browser Extension Mode

In this mode, the extension runs in the user's browser and uses the marketplace
session that already exists in that browser.

Allowed behavior:

- The user explicitly enables Price Assistant import.
- The extension runs only on supported marketplace domains with least-privilege
  host permissions.
- The extension uses the user's current marketplace login state in the browser.
- The extension locally extracts cart, favorites, or product-page items from:
  - visible DOM;
  - page data available to the same-origin marketplace page;
  - same-origin responses already available to the browser context.
- The extension sends only a sanitized item list to the WordPress proxy.

Sanitized item fields should be limited to:

- `product_url`;
- `title`;
- `price`;
- `currency`;
- `quantity`;
- `source`;
- `import_type`.

Prohibited behavior:

- Do not read or send marketplace cookies.
- Do not read or send WordPress auth cookies.
- Do not read or send passwords, auth tokens, refresh tokens, local storage
  secrets, session storage secrets, or full private HTML.
- Do not call FastAPI directly from the extension.
- Do not bypass captcha, fingerprinting, bot checks, or access controls.

The extension is a local collection tool, not a remote account automation tool.

## Mode 2: Device-Local Mobile WebView Mode

In this mode, a mobile application opens the real marketplace page in a WebView
or custom tab. The user signs in directly with the marketplace.

Allowed behavior:

- The marketplace login page is controlled by the marketplace, not by Savello.
- The app does not receive or store the marketplace password.
- Session cookies remain in the protected browser/WebView storage on the
  device.
- The app locally reads or parses cart/favorites/product-page data that is
  visible or available in the device-local marketplace context.
- The app sends only a sanitized item list to the WordPress proxy.

Sanitized item fields should match the browser extension mode:

- `product_url`;
- `title`;
- `price`;
- `currency`;
- `quantity`;
- `source`;
- `import_type`.

Prohibited behavior:

- Do not extract marketplace passwords.
- Do not upload marketplace cookies or account tokens to WordPress or FastAPI.
- Do not call FastAPI directly from the mobile app.
- Do not persist raw private marketplace pages on the backend.
- Do not bypass captcha, fingerprinting, bot checks, or access controls.

This mode keeps marketplace authentication and session material on the device.
The backend receives only normalized product candidates.

## Mode 3: High-Risk Remote Session Mode

This mode would store encrypted marketplace session cookies on the server and
let the server refresh carts or favorites remotely.

Under the current `spec.md`, this mode is rejected/deferred and must not be
implemented for MVP. The active specification says the server must never store
marketplace passwords, marketplace session cookies, auth cookies, refresh
tokens, or private marketplace credentials. It also prohibits server-side
marketplace account login, cookie replay, and password-based import.

Any future reconsideration requires a separate explicit change to the
specification and all of the following gates before any code is written:

- separate user consent for each marketplace;
- updated privacy policy;
- legal approval;
- security review;
- data protection impact review;
- per-marketplace kill switch;
- feature flag disabled by default;
- no captcha or fingerprint bypass.

Minimum guards if a future approved ADR ever allows this mode:

- cookies/tokens encrypted at rest with authenticated encryption;
- strict TTL and reconnect requirement;
- rotation of stored session material;
- user-visible revoke/disconnect;
- per-marketplace kill switch;
- strict rate limits and cost controls;
- source cooldown and quarantine integration;
- logs and metrics redacted so they never include cookies, tokens, passwords,
  proxy credentials, account identifiers, or raw private page content;
- no captcha bypass, fingerprint bypass, or prohibited access mechanisms.

This document does not approve Remote Session Mode. It records why it is high
risk and outside the MVP.

## DB Proposal

This is a conceptual proposal only. It does not create migrations.

For the Device-Local MVP, the service should only need records that represent
safe import metadata and sanitized item processing status:

- import batch identity;
- WordPress `site_id`;
- WordPress-derived `external_user_id`;
- `source`;
- `import_type`;
- `consent_version`;
- `collected_at`;
- item count;
- per-item sanitized URL/title/price/currency/quantity;
- per-item status such as accepted, already tracked, unsupported source,
  invalid URL, or rejected.

The MVP database design must not include marketplace passwords, marketplace
cookies, auth cookies, refresh tokens, local storage secrets, session storage
secrets, or raw private HTML.

If a future ADR ever reopens Remote Session Mode, its hypothetical tables must
be separate from the MVP import tables and marked `NOT FOR MVP`. They would need
encrypted session material, TTL, rotation, reconnect, revoke/disconnect,
marketplace kill switch, audit, and strict access controls. Those tables must
not be added under the current specification.

## API Proposal

Device-local connectors should use the planned WordPress proxy import endpoint
from `spec.md`:

```http
POST /wp-json/cashback/v1/price-assistant/import
```

Authentication:

- WordPress logged-in user session.
- Nonce or extension-authenticated WordPress cookie flow for browser extension
  imports.
- WordPress signs upstream FastAPI calls server-side with the existing HMAC
  headers.

Request shape:

```json
{
  "source": "ozon",
  "import_type": "cart",
  "consent_version": "price-assistant-import-v1",
  "collected_at": "2026-06-15T05:00:00Z",
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

Allowed `import_type` values:

- `cart`;
- `favorites`;
- `product_page`;
- `manual_file`.

Prohibited payload fields:

- marketplace cookies;
- WordPress auth cookies;
- passwords;
- auth tokens;
- refresh tokens;
- marketplace local storage secrets;
- marketplace session storage secrets;
- full HTML snapshots containing private account data.

FastAPI public API behavior should not change for this architecture document.
The WordPress proxy remains the only browser/mobile-facing integration boundary.

## Threat Model

| Threat | Risk | Mitigation |
| --- | --- | --- |
| Cookie or token exfiltration | Marketplace account compromise | Device-local modes never send cookies, passwords, auth tokens, refresh tokens, local storage secrets, or session storage secrets to backend |
| Extension or mobile overcollection | Private account data leakage | Explicit consent, least-privilege host permissions, sanitized field allowlist, no full private HTML upload |
| Client-forged import payload | Invalid products, abuse, poisoning | WordPress auth boundary, nonce/session validation, server-derived `site_id` and `external_user_id`, schema validation |
| IDOR through user/site spoofing | Cross-user watchlist access | WordPress must not accept client-provided user identity; FastAPI HMAC and `site_id + external_user_id` scoping stay in force |
| Stored XSS or CSV injection | Unsafe imported titles or exported data | Treat titles as untrusted, escape on output, harden CSV cells, reject oversized payloads |
| Replay or duplicate imports | Duplicate subscriptions or noisy processing | Import batch identity, per-item deduplication against existing subscriptions, idempotent item handling |
| Backend SSRF through product URLs | Internal network access from backend | Source allowlist, URL normalizer, unsupported source rejection, no arbitrary URL fetch from import data |
| High-cost fetch loops | Source bans and cost spikes | Existing scheduler limits, source health, cooldown, quarantine, proxy cost budget, duplicate queued/running guards |
| Captcha pressure | Forbidden escalation or unstable automation | No captcha/fingerprint bypass; captcha-like events quarantine source and stop escalation |
| Sensitive logs or metrics | Privacy and credential exposure | Structured redacted logging; no cookies, tokens, passwords, proxy endpoint refs, or raw private HTML in logs/metrics |

## Recommendation

Build MVP import only through Device-Local Browser Extension Mode and
Device-Local Mobile WebView Mode.

Do not implement High-Risk Remote Session Mode under the current specification.
If the business later wants server-stored marketplace sessions, that must be a
separate legal/security/specification project before any engineering work.
