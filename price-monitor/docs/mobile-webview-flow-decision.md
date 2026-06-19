# Mobile WebView Flow Decision

Date: 2026-06-19
Status: ADR-first gate, not implementation

## Decision

Mobile Price Assistant connection uses **WebView-only capture**.

The Savello mobile app opens the real marketplace web page inside an app-owned
WebView, waits for the user to authenticate on that marketplace page, shows
source-specific consent, extracts only allowlisted cookies/tokens from that
WebView context, and uploads the minimized session bundle through the existing
WordPress proxy.

The mobile app не извлекает cookies/tokens из нативных приложений Ozon/WB/Yandex Market.
Android and iOS isolate application data, and there is no approved,
safe, platform-supported path for reading another marketplace app's session
storage. Native marketplace app handoff may be used only as a non-capturing UX
fallback; it does not produce a session bundle.

This decision does not approve any real Ozon, Wildberries, or Yandex Market
cookie/token names. Those allowlists remain empty/no-go until separate
legal/security/source approval records exist.

## Mobile API Contract

The mobile client uses only the existing WordPress REST proxy:

- `GET /wp-json/cashback/v1/price-assistant/consent`
- `POST /wp-json/cashback/v1/price-assistant/connections`
- `POST /wp-json/cashback/v1/price-assistant/connections/{connection_id}/session-bundle`
- `GET /wp-json/cashback/v1/price-assistant/sync-status`
- `DELETE /wp-json/cashback/v1/price-assistant/connections/{connection_id}`

The mobile client never calls the internal price-monitor service, never sees
FastAPI HMAC secrets, internal backend URLs, `site_id`, or `external_user_id`.
WordPress remains the owner-scoped boundary and derives the user identity from
the logged-in Savello/WordPress session.

Connection create request:

```json
{
  "marketplace": "ozon",
  "consent_version": "price-assistant-session-v1",
  "scope": ["cart_read", "favorites_read"],
  "captured_at": "2026-06-19T10:00:00Z",
  "connector_version": "savello-mobile-webview-0.1.0"
}
```

Session bundle upload request:

```json
{
  "consent": true,
  "marketplace": "ozon",
  "consent_version": "price-assistant-session-v1",
  "scope": ["cart_read", "favorites_read"],
  "captured_at": "2026-06-19T10:03:00Z",
  "connector_version": "savello-mobile-webview-0.1.0",
  "session_bundle": {
    "cookies": [
      {
        "name": "allowlisted_cookie_name",
        "value": "secret",
        "domain": ".ozon.ru",
        "path": "/",
        "secure": true,
        "httpOnly": true
      }
    ],
    "tokens": [
      {
        "name": "allowlisted_token_name",
        "value": "secret"
      }
    ],
    "captured_at": "2026-06-19T10:03:00Z",
    "user_agent_hint": "SavelloMobileWebView/0.1.0",
    "region_hint": "default"
  }
}
```

The connector must not send:

- marketplace password or login form values;
- Savello, WordPress, or WooCommerce cookies;
- browser password-manager data;
- full `localStorage` or `sessionStorage` dumps;
- raw marketplace HTML or private page snapshots;
- payment, passport, identity, or financial data;
- non-allowlisted cookies/tokens.

Только HTTPS/TLS is allowed for mobile uploads. Sensitive URL values, cookies,
tokens, request bodies, and response bodies must not be written to logs,
analytics, crash reports, screenshots, or UI diagnostics.

## UX States

Mobile-only states are local app states and are not persisted as backend status:

- `marketplace_selected`
- `connection_creating`
- `webview_login_open`
- `login_observed`
- `consent_pending`
- `bundle_extracting`
- `bundle_uploading`
- `upload_failed_safe`
- `disconnect_confirming`
- `local_session_clearing`

Backend/public states remain unchanged:

- `connecting`
- `connected`
- `sync_failed_retryable`
- `source_limited`
- `reconnect_required`
- `disconnected`

Consent показывается после подтвержденного входа on the real marketplace page
and before the session-bundle upload. If the user denies consent, closes the
WebView, permissions fail, no allowlisted values are found, or the source is
disabled, the app must not upload partial secrets.

Disconnect flow:

1. Ask for user confirmation.
2. Call the WordPress `DELETE` endpoint for the owned connection.
3. Delete any temporary encrypted local bundle.
4. If the user selects full local cleanup, clear WebView cookies, session
   cookies, WebView storage/cache, and in-memory connector state for this flow.

`401`, `403`, `login_required`, and `expired` map to `reconnect_required`.
Captcha, bot detection, fingerprint challenge, block, and rate-limit signals
stop the connector or sync safely as `source_limited`/safe stopped. They must
not trigger captcha solving, fingerprint evasion, access-control bypass, or
aggressive retry loops.

## Android Security Notes

- Read only cookies from the app-owned WebView using Android CookieManager.getCookie
  for the selected marketplace URL, then filter by the source-specific
  allowlist before building the bundle.
- Clear WebView cookies through `CookieManager.removeAllCookies(...)` and
  session cookies through `CookieManager.removeSessionCookies(...)` when the
  user requests cleanup on disconnect.
- Do not store secrets in external storage. If a temporary local bundle is
  needed before upload, encrypt it with an app-owned key protected by Android
  Keystore and delete it after upload, denial, failure, or disconnect.
- Do not inspect another Android app's private data, cookie store, backup data,
  accessibility tree, notification contents, or exported files to obtain
  marketplace sessions.

## iOS Security Notes

- Use `WKWebView` with an isolated `WKWebsiteDataStore` for the connector flow.
- Read only cookies from that WebView using `WKHTTPCookieStore`, then filter by
  the approved allowlist before upload.
- Clear connector cookies and website data from the selected `WKWebsiteDataStore`
  on disconnect when the user requests full local cleanup.
- `ASWebAuthenticationSession` is allowed only for browser/app handoff that does
  not capture a session bundle. Ephemeral sessions are useful for isolated
  authentication, but they do not provide the connector with cookies to upload.
- If a temporary local bundle is unavoidable, protect it with Keychain/Data
  Protection and delete it after upload, denial, failure, or disconnect.
- Do not inspect another iOS app's container, pasteboard, keychain items, app
  group storage, or universal-link handoff data to obtain marketplace sessions.

## Contract Test Scenarios

Future mobile implementation must cover these scenarios before production:

- consent denied: no upload request is sent;
- password, login form values, local storage, session storage, and raw HTML are
  rejected before upload;
- non-allowlisted values are dropped and never encrypted;
- bundle with no allowlisted values fails closed;
- source disabled blocks create/upload;
- disconnect calls WordPress delete and clears local temporary secrets;
- `401`/`403`/`login_required`/`expired` maps to `reconnect_required`;
- captcha/block/fingerprint/rate-limit signal stops safely and does not retry
  aggressively or bypass controls;
- mobile logs and crash payloads contain no cookies/tokens/sensitive URLs;
- no native marketplace app cookie/token interception path exists.

## References Checked

- Android CookieManager:
  https://developer.android.com/reference/android/webkit/CookieManager
- Android Security Checklist:
  https://developer.android.com/privacy-and-security/security-tips
- Android Keystore:
  https://developer.android.com/privacy-and-security/keystore
- Apple WKHTTPCookieStore:
  https://developer.apple.com/documentation/webkit/wkhttpcookiestore
- Apple WKHTTPCookieStore getAllCookies:
  https://developer.apple.com/documentation/webkit/wkhttpcookiestore/getallcookies(_:)
- Apple ASWebAuthenticationSession:
  https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession
- Apple ASWebAuthenticationSession ephemeral browser sessions:
  https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession/prefersephemeralwebbrowsersession
- Apple App Sandbox:
  https://developer.apple.com/documentation/security/app-sandbox

## Explicit Non-Goals

This ADR does not implement mobile code, WebView code, WordPress code, FastAPI
code, migrations, marketplace adapters, sync worker behavior, public API changes,
real marketplace allowlist names, legal approval, source approval, or production
enablement for Ozon, Wildberries, or Yandex Market.
