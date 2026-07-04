# Affiliate Feed Price Search Design

## Goal

Build a production-ready product search and price comparison service that uses approved Admitad and AdvCake product feeds as the primary catalog source, keeps WordPress as the owner of encrypted CPA credentials and affiliate link generation, and uses live checks only as a freshness/region verification layer.

## Evidence

Primary sources checked on 2026-07-04:

- Admitad/Mitgo Publisher API exposes program feed metadata through `show_products_links`, `products_xml_link`, `products_csv_link`, and `feeds_info`: https://developers.mitgo.com/hc/en-us/articles/34481349447058-Affiliate-programs
- Admitad XML Feed is intended for importing structured product data into publisher sites/apps/tools: https://www.admitad.com/affiliates/
- Mitgo product feed docs describe catalog fields and state that Admitad feeds are updated every 6 hours: https://support.mitgo.com/hc/en-us/articles/33311956438546-Product-feed-what-it-is-and-how-to-upload-it-to-affiliate-program
- Admitad Deeplink API generates affiliate links for product URLs through `ulp`: https://developers.mitgo.com/hc/en-us/articles/34481332881938-Deeplink-generator
- AdvCake Publisher API exposes `common-feeds` and saved `feeds`, plus Cakelink for deeplink conversion: https://support.advcake.com/docs/api/publisher-api/
- AdvCake product feed docs describe YML/XML product fields; `available` is documented as always true and cannot be treated as real stock: https://support.advcake.com/docs/advdocs/product-feeds-description/
- Awin and Rakuten docs confirm the industry pattern: product feeds are used by price comparison publishers and affiliate networks; feed freshness and completeness depend on merchant sources: https://help.awin.com/developers/docs/product-feed-publisher-guide-intro and https://pubhelp.rakutenadvertising.com/hc/en-us/articles/7145964532877-Data-Feeds
- Sovrn Price Comparison API documents the same architecture in API form: product URL/barcode/keyword matching over normalized merchant feeds/APIs, with freshness from near real-time to daily and possible missing fields: https://developer.sovrn.com/reference/product-affiliate-api

## Architecture

The service remains feed-first. Feeds build a local search index of product candidates and price snapshots. Live search adapters are not the primary discovery path; they are used only to refresh high-value candidates, selected watchlist items, or stores that have explicit approved live providers.

WordPress remains the only process that can decrypt existing CPA network credentials. The backend never receives raw Admitad `client_secret`, AdvCake `api_key`, or WordPress `CB_ENCRYPTION_KEY`. Backend-to-WordPress calls use the existing internal HMAC pattern, and WordPress returns only redacted metadata, feed download jobs/results, normalized product rows, or generated affiliate URLs.

Affiliate tracking is separated from product data. Search results should contain plain product URLs and offer metadata. Affiliate links are generated on click-out by WordPress using existing Admitad Deeplink or AdvCake Cakelink behavior.

## Components

### WordPress Credential Bridge

Add a server-only price comparison CPA bridge in the plugin. It should expose internal methods and REST/WP-CLI entry points for:

- `network_status`: whether Admitad/AdvCake credentials exist and can authenticate.
- `list_feed_sources`: feed metadata for enabled programs without returning secret-bearing feed URLs to the browser.
- `download_feed`: fetch a configured feed through WordPress or return a temporary backend-readable feed handoff token that cannot reveal CPA credentials in logs.
- `create_affiliate_link`: create Admitad deeplink or AdvCake Cakelink for a product URL and tracking payload.

Credential storage already exists:

- CPA credentials are stored in `wp_cashback_affiliate_networks.api_credentials`.
- `Cashback_API_Client::get_credentials()` decrypts the JSON payload.
- `Cashback_Encryption` uses `CB_ENCRYPTION_KEY`, `CB_ENCRYPTION_KEY_NEW`, and `CB_ENCRYPTION_KEY_PREVIOUS`.
- Admitad credentials use `client_id`, `client_secret`, and `scope`.
- AdvCake credentials use `api_key`.

### Backend Feed Catalog

Extend the current `price_compare` domain with feed source records, feed import runs, normalized offer fields, and price snapshots. Current `StoreSource`, `Offer`, and `ImportStatus` stay; new fields/tables should add:

- feed metadata: network, program ID, feed ID, format, last advertised update, last imported hash.
- product identity: GTIN/barcode, vendor code, model, old price, raw category ID, params.
- freshness: source freshness, `feed_last_update`, `last_live_checked_at`, `freshness_status`.
- region: `region_scope`, city if known, and `region_verified`.

### Search And Matching

Search first queries the local index. Ranking uses:

1. exact barcode/GTIN if available;
2. exact normalized vendor/model/title tokens;
3. title token relevance;
4. availability/freshness;
5. final price including known cashback only when confidence allows it.

No result may claim full regional availability unless a region-specific source or live refresh confirms it.

### Live Freshness

Live refresh is bounded and fail-closed:

- refresh top candidates, watchlist items, or explicit store adapters;
- record `LIVE_VERIFIED`, `REGION_UNVERIFIED`, `STALE_FEED`, `BLOCKED_BY_ANTIBOT`, or `LIVE_UNAVAILABLE`;
- stop immediately on 403/429/captcha/robot markers;
- do not add captcha solving, hidden fingerprint evasion, credential stuffing, or unbounded proxy rotation.

### WordPress UI

User-facing UI stays in WordPress:

- browser JavaScript calls only WordPress REST;
- WordPress proxies search/start/poll requests to the backend;
- WordPress creates affiliate links server-side on click-out;
- UI labels source and freshness clearly: feed price, updated time, live verified, region unverified, blocked source.

## Error And Safety Model

- Raw CPA credentials, feed URLs containing secrets, HMAC secrets, and encryption keys must not appear in repo, browser payloads, logs, REST errors, test fixtures, screenshots, or docs.
- Feed URLs returned by Admitad/AdvCake are treated as secrets when they include tokens or codes.
- Failed credential decrypt returns a safe "credentials unavailable" status.
- A protected store that returns anti-bot evidence is not retried with evasion.
- Feed coverage is not assumed full-catalog unless the feed metadata and imported row count prove practical coverage for that store.

## Test Strategy

- Backend unit tests cover feed metadata models, parsers, normalizers, import idempotency, freshness statuses, search ranking, and no-secret redaction.
- WordPress PHPUnit tests cover credential bridge auth, existing encrypted credential reads through `Cashback_API_Client`, redaction, feed metadata response shape, and affiliate link dispatch.
- Node tests cover safe DOM rendering and no backend secret exposure.
- Integration tests on the test server verify Admitad/AdvCake network status and one feed metadata pull without printing secrets.
- Browser smoke verifies the account UI through WordPress REST only.

## Rollout

1. Implement safe credential/feed bridge in WordPress with no raw secret egress.
2. Implement backend feed source/import models and parsers.
3. Add Admitad connector through the bridge.
4. Add AdvCake connector through the bridge.
5. Add freshness-aware search and live refresh integration.
6. Add WordPress admin/user UI states.
7. Verify locally, push feature branches, cherry-pick backend to `develop` for test deploy, run CI/deploy, and smoke on the test server.

## Open Decisions

- Saved AdvCake feeds may require manual preparation in the AdvCake cabinet. If no saved/common feed exists for a target program, the UI must show "feed not configured".
- Some feed downloads may be too large for synchronous WordPress-to-backend transfer. The implementation should support async jobs and chunked/streamed parsing.
- Region-specific prices should remain unverified unless a feed carries region data or a live/official source verifies the city.
