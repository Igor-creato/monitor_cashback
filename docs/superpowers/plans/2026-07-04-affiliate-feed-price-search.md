# Affiliate Feed Price Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** build a production-ready product search and price comparison service that uses approved Admitad and AdvCake product feeds for catalog coverage, keeps CPA credentials inside WordPress encryption boundaries, generates affiliate links server-side, and uses live checks only as a bounded freshness layer.

**Architecture:** WordPress owns affiliate-network credentials and deeplink/cakelink generation. The backend owns normalized catalog ingestion, search, matching, price history, live freshness checks, and the signed API consumed by WordPress. Browser JavaScript talks only to WordPress REST endpoints.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic/Celery in `F:/cash-back/monitor_cashback`; WordPress/PHP/PHPUnit/JavaScript in `F:/wamp64/www/kash-back/wp-content/plugins/cash-back`.

## Global Constraints

- Prefix every shell command with `rtk`.
- Use strict RED -> GREEN TDD: add the smallest failing test, prove it fails, then implement the minimum code and prove it passes.
- Keep backend and WordPress plugin branches separate:
  - backend: `feature/price-compare-search-service`
  - plugin: `feature/price-compare-search-wordpress`
- Never commit raw API keys, decrypted credentials, HMAC secrets, feed token URLs, proxy passwords, encryption keys, or fixture copies that contain them.
- Treat product feed URLs from affiliate networks as secrets if they include tokens, passwords, or publisher identifiers.
- Do not expose backend URL or backend HMAC secret to browser JavaScript. Browser code calls WordPress REST only.
- Do not bypass captchas, fingerprinting, anti-bot systems, or infinite proxy rotation. Live fetchers stop on explicit anti-bot evidence.
- Feed data is the discovery/index source. Live search is freshness verification, not a substitute for full catalog ingestion.
- Region support must be explicit per source/feed. If a feed does not prove regional coverage, return `region_supported=false` or an explanatory source status instead of pretending coverage.
- Preserve existing WordPress credential storage contracts:
  - `wp_cashback_affiliate_networks.api_credentials` stores encrypted JSON.
  - `Cashback_API_Client::get_credentials()` is the safe read path.
  - encryption uses `Cashback_Encryption` and existing constants/options.
- Do not change existing public redirect/activation contracts unless a task explicitly requires it.

## Evidence From Research

- Admitad/Mitgo affiliate programs expose feed-related metadata such as `show_products_links`, `products_xml_link`, `products_csv_link`, `feeds_info`, `admitad_last_update`, and `advertiser_last_update`.
- Admitad product-feed guidance describes feeds as structured product data for import into sites/apps/tools; documented update cadence is around 6 hours, not real time.
- Admitad Deeplink API can generate affiliate links from product URLs through `ulp`; batching up to 200 links is documented.
- AdvCake publisher API exposes `common-feeds` and saved `feeds`; feed records include feed IDs, formats, offer IDs, product counts, download/update timestamps, and URLs.
- AdvCake feed format is YML/XML-like and includes product URL, name, vendor/model, category, price, old price, currency, pictures, barcode, params, and `available`. Their docs state `available` is always true, so stock freshness must not rely on it.
- Top cashback services usually provide store/coupon/cashback activation search, while product comparison services combine merchant feeds, indexed product catalogs, extension/page signals, price history, and server-side affiliate link generation.

## End State

- WordPress internal HMAC routes expose safe CPA network/feed/deeplink capabilities to the backend without returning decrypted credentials.
- Backend imports Admitad and AdvCake product feeds into normalized offer/search tables.
- Search returns ranked offers with source freshness, region confidence, price timestamp, and safe clickout metadata.
- WordPress user UI searches via WordPress REST, displays offers/freshness/source status, and resolves affiliate clickout server-side.
- Admin UI shows feed health/import status and can trigger or inspect sync without exposing secrets.
- Local gates, CI, test-server backend smoke, and WordPress browser smoke are documented before final completion.

## Task 1: WordPress CPA Credential Bridge, Read-Only Status

**Repo:** `F:/wamp64/www/kash-back/wp-content/plugins/cash-back`

**Files to inspect first:**

- `includes/class-cashback-api-client.php`
- `includes/class-cashback-encryption.php`
- `includes/adapters/class-admitad-adapter.php`
- `includes/adapters/class-cashback-advcake-adapter.php`
- `includes/services/class-cashback-internal-api-service.php`
- `includes/rest/class-cashback-internal-rest-controller.php`
- existing PHPUnit bootstrap/tests under `development/test`

**Tests first:**

- Add a focused PHPUnit test for a new bridge service that uses an injectable fake API client.
- RED assertions:
  - `admitad` status is `configured=true` when encrypted/stub credentials contain `client_id` and `client_secret`.
  - `advcake` status is `configured=true` when credentials contain `api_key`.
  - JSON output never contains `api_key`, `client_secret`, `client_id`, `password`, `token`, or decrypted values.
  - missing/invalid credentials produce `configured=false` with a non-secret reason code.

**Implementation:**

- Add `Cashback_Price_Comparison_CPA_Bridge` under `includes/price-comparison/`.
- Use `Cashback_API_Client::get_credentials()` or an injected compatible object.
- Return only capability/status metadata:
  - network slug
  - configured flag
  - supported capabilities: `product_feeds`, `deeplink`
  - credential health code
  - adapter/source labels
- Register/load the class through the plugin bootstrap path already used by price-comparison classes.

**Verification:**

- Run the focused PHPUnit test.
- Run `rtk git diff --check` in the plugin repo.

## Task 2: WordPress Internal HMAC CPA Feed and Deeplink Routes

**Repo:** `F:/wamp64/www/kash-back/wp-content/plugins/cash-back`

**Tests first:**

- Add REST controller tests around the internal namespace `savello-internal/v1`.
- RED assertions:
  - unauthenticated calls are rejected by the existing internal HMAC permission flow.
  - `/price-comparison/cpa/networks` returns redacted network status.
  - `/price-comparison/cpa/feeds` returns feed descriptors but never raw credential values.
  - `/price-comparison/cpa/deeplink` returns an affiliate URL for allowed source URLs through the existing network adapters.
  - invalid domains/network slugs fail closed.

**Implementation:**

- Extend `Cashback_Internal_REST_Controller`.
- Add bridge methods for:
  - network status list
  - feed descriptor discovery for Admitad and AdvCake
  - affiliate-link creation for a source product URL
- Reuse existing adapters where possible:
  - Admitad adapter deeplink flow
  - AdvCake cakelink flow
- Ensure every route is internal-HMAC-only.
- Redact or omit feed URLs if they contain credentials. If backend must fetch them directly, return them only over signed internal HMAC and mark them secret in logs.

**Verification:**

- Run the focused REST/PHPUnit tests.
- Run existing price-comparison PHPUnit tests if present.
- Confirm no secrets appear in test output or snapshots.

## Task 3: Backend WordPress Internal Bridge Client

**Repo:** `F:/cash-back/monitor_cashback`

**Files to inspect first:**

- `src/price_monitor/core/config.py`
- `src/price_monitor/security.py`
- `src/price_monitor/api/v1/search.py`
- `src/price_monitor/price_compare/feed.py`
- existing HTTP client patterns and tests

**Tests first:**

- Add unit tests with `httpx.MockTransport` or the existing test transport style.
- RED assertions:
  - client signs requests exactly like WordPress internal HMAC expects: `HMAC(secret, timestamp + raw_body)`.
  - headers include `X-Savello-Site`, `X-Savello-Timestamp`, and `X-Savello-Signature`.
  - client rejects disabled/missing settings with a typed unavailable result.
  - response logging/redaction never includes secrets or feed token URLs.

**Implementation:**

- Add backend settings for WordPress internal bridge base URL/site/secret/timeout using the existing `PRICE_MONITOR_` env prefix.
- Add a dedicated client module for WordPress internal price-comparison CPA endpoints.
- Keep this signer separate from the backend public API HMAC signer because the contracts differ.
- Add typed DTO/schema helpers for network status, feed descriptors, and deeplink responses.

**Verification:**

- Run the focused backend unit tests.
- Run `rtk python -m ruff check` on touched files if available.

## Task 4: Backend Feed Source Models and Migration

**Repo:** `F:/cash-back/monitor_cashback`

**Tests first:**

- Add model/repository tests against the project test DB pattern.
- RED assertions:
  - an affiliate feed source can be stored without raw network credentials.
  - feed descriptor uniqueness prevents duplicate imports for the same network/offer/feed identity.
  - import runs record status, counts, timestamps, and source freshness.
  - secret feed URLs are not included in public serialization.

**Implementation:**

- Add or extend SQLAlchemy models for:
  - affiliate feed source descriptors
  - feed import runs
  - optional price snapshots if existing `Offer` history does not already cover this
- Add Alembic migration after the current head.
- Keep normalized offers compatible with existing `Offer` search serialization.
- Store hashes or references for secret feed URLs when possible; if a URL must be persisted, mark the column/internal serializer as secret and never expose it through public APIs.

**Verification:**

- Run the focused model/repository tests.
- Run Alembic upgrade/downgrade check locally if the repo has an established command.

## Task 5: Admitad and AdvCake Feed Parsers

**Repo:** `F:/cash-back/monitor_cashback`

**Tests first:**

- Add parser fixtures with synthetic, non-secret XML/CSV/YML snippets.
- RED assertions:
  - Admitad CSV and/or XML maps title, product URL, image, price, currency, category, brand, external ID, and timestamps.
  - AdvCake YML/XML maps URL, name/vendor/model, category, price, old price, currency, picture, barcode, params.
  - AdvCake `available=true` is normalized as `unknown` or low-confidence stock, not real stock proof.
  - rows with invalid price/currency are skipped or quarantined with reason codes.
  - parser output contains no affiliate-network credentials.

**Implementation:**

- Split parser logic from import orchestration if needed.
- Add feed-format detection by descriptor metadata and content-type.
- Normalize product URLs before deeplink generation; do not rewrite them in the parser.
- Preserve source raw payload hashes for change detection.

**Verification:**

- Run focused parser tests.
- Run existing `price_compare` feed tests to ensure current campaign-only fallback behavior is not broken.

## Task 6: Feed Import Orchestrator and Celery Task

**Repo:** `F:/cash-back/monitor_cashback`

**Tests first:**

- Add service tests using fake bridge client and fake feed downloader.
- RED assertions:
  - import discovers configured Admitad/AdvCake feeds from WordPress.
  - import downloads/parses/upserts offers idempotently.
  - import records counts for created/updated/skipped/quarantined rows.
  - network unavailable and feed parse failures produce source status instead of crashing search.
  - secret URLs are redacted from logs/errors.

**Implementation:**

- Add an import service that:
  - asks WordPress bridge for safe feed descriptors
  - downloads feeds using backend HTTP client with timeouts and size limits
  - parses by source format
  - upserts offers by source/feed/external product identity
  - records import run metrics
- Add Celery task and optional admin-trigger entrypoint.
- Keep scheduling conservative until feed health is proven on the test server.

**Verification:**

- Run focused service/task tests.
- Run `rtk python -m ruff check` on touched backend files.

## Task 7: Search Ranking, Freshness, and Region Semantics

**Repo:** `F:/cash-back/monitor_cashback`

**Tests first:**

- Add API/service tests around `/api/v1/search`.
- RED assertions:
  - indexed feed offers are returned for matching queries.
  - response includes `price_updated_at`, `feed_updated_at` or equivalent freshness fields.
  - region-unknown feed results are clearly marked and do not claim city-specific coverage.
  - if index is empty, existing `SEARCH_INDEX_EMPTY` behavior remains.
  - source-level feed health appears in `store_statuses` without leaking secrets.

**Implementation:**

- Extend search serialization minimally.
- Add ranking boosts for exact/normalized title match, lower price, recent update, and configured region confidence.
- Keep source status codes stable and explicit.
- Integrate live freshness checks only after feed search produces candidates, and stop on anti-bot evidence.

**Verification:**

- Run focused API tests.
- Run existing search tests.

## Task 8: WordPress Backend Search Integration and Clickout Flow

**Repo:** `F:/wamp64/www/kash-back/wp-content/plugins/cash-back`

**Tests first:**

- Add/extend service tests around `Cashback_Price_Comparison_Service`.
- RED assertions:
  - user-facing REST search still calls only WordPress server-side code.
  - result enrichment can request affiliate clickout server-side without exposing backend HMAC.
  - backend item metadata is escaped/sanitized before response.
  - source/freshness fields are preserved for UI.

**Implementation:**

- Extend the existing price-comparison client/service instead of adding a parallel public flow.
- Add a server-side clickout/resolve route if the current direct-product-link path cannot support backend feed offers.
- Use existing nonce/capability patterns for user-facing routes.
- Keep current admin settings names unless a backward-compatible alias is needed.

**Verification:**

- Run focused PHPUnit tests.
- Run JS build/lint only if touched.

## Task 9: WordPress Admin and User UI

**Repo:** `F:/wamp64/www/kash-back/wp-content/plugins/cash-back`

**Tests first:**

- Add PHP/JS tests where existing tooling supports them; otherwise add focused PHP tests for generated data and run browser smoke after deploy.
- RED assertions:
  - admin page/status widget displays network/feed health without secrets.
  - user results display price, store, freshness/region confidence, and source status.
  - empty/blocked/unavailable states are user-readable.

**Implementation:**

- Reuse existing price assistant/admin UI patterns.
- Add feed health/import status to the admin monitoring surface.
- In user UI, keep the first screen as the actual product search experience.
- Do not add in-browser backend credentials, feed URLs, or direct CPA API calls.

**Verification:**

- Run focused plugin tests.
- Use browser smoke on the test WordPress site after deploy.

## Task 10: End-to-End Gates, Deploy, and Server Smoke

**Repos:** backend and plugin

**Local backend gates:**

- `rtk python -m pytest`
- `rtk python -m ruff check .`
- `rtk python -m ruff format --check .`
- `rtk python -m mypy`
- `rtk python -m pip check`
- `rtk docker compose config --quiet`
- `rtk git diff --check`

**Local plugin gates:**

- focused PHPUnit tests added by this plan
- existing price-comparison PHPUnit tests
- JS build/lint if UI assets are touched
- `rtk git diff --check`

**Deploy:**

- Commit backend changes on `feature/price-compare-search-service`.
- Commit plugin changes on `feature/price-compare-search-wordpress`.
- Push feature branches.
- If test deploy consumes `develop`, cherry-pick reviewed backend commit(s) to `develop`, run gates, push `develop`, and wait for CI/deploy.
- Deploy or update the plugin on the test WordPress site using the established repo workflow only.

**Server smoke:**

- Check release path: `/home/igor/monitor_cashback/current`.
- Check `/health/live` and `/health/ready`.
- Verify backend can import the new bridge/feed modules inside the running container.
- Configure one low-risk test feed source from WordPress credentials without printing the secret URL.
- Run one backend search smoke and capture:
  - query
  - city
  - run/import IDs
  - result count
  - source statuses
  - freshness fields
- Run WordPress browser smoke as a temporary user only after backend smoke succeeds.
- Remove temporary users/debug scripts after smoke.

**Final report must include:**

- changed files by repo
- tests/gates run and exact result
- commit hashes for backend/plugin and any develop cherry-pick
- CI/deploy run links or IDs
- test server release path
- feed/source configuration summary with secrets redacted
- backend search smoke result
- WordPress browser smoke result
- explicit note if any task could not be verified
