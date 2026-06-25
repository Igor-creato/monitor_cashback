# Product Link Monitoring Readiness

Date: 2026-06-25
Scope: product monitoring by URL only

This report tracks the production-readiness state for the requested product-link
monitoring stores. It does not cover cart/favorites sync, product search, or
cross-store comparison.

## Current Capability

- Users can add supported product URLs through the existing watchlist API.
- Product URL normalization is moving to a store registry.
- Price fetch, image storage, price history, chart data, and price-change
  notifications use the existing backend pipeline.
- Unsupported or access-gated stores fail closed and are listed below with a
  reason.

## Store Support Matrix

| Store | Code | State | Strategy | Reason |
| --- | --- | --- | --- | --- |
| Wildberries | `wildberries` | supported | structured_data | First safe registry-backed URL normalization path; extraction remains fixture-gated before production enablement. |
| Ozon | `ozon` | requires_access | none | Official consumer product-price API is not approved. |
| Yandex Market | `yandex_market` | requires_access | none | Documented price/stock APIs require seller API-key scoped access. |
| DNS | `dns` | requires_access | none | Stable public product data source is not approved. |
| Samokat | `samokat` | requires_access | none | Grocery catalog depends on region/session data. |
| VkusVill | `vkusvill` | requires_access | none | Regional catalog stability requires source approval. |
| Vseinstrumenti | `vseinstrumenti` | requires_access | none | Official/feed path is not configured. |
| Yandex Lavka | `yandex_lavka` | requires_access | none | Grocery catalog depends on region/session data. |
| Gold Apple | `goldapple` | requires_access | none | Stable public product data source is not approved. |
| Lamoda | `lamoda` | requires_access | none | Feed/API access needs source approval. |
| ETM | `etm` | requires_access | none | B2B catalog pricing may require account context. |
| Pyaterochka | `pyaterochka` | requires_access | none | Grocery catalog depends on region/session data. |
| Citilink | `citilink` | requires_access | none | Stable public product data source is not approved. |
| Kuper | `kuper` | requires_access | none | Grocery catalog depends on region/session data. |
| Yandex Eda | `yandex_eda` | requires_access | none | Marketplace data depends on region/session data. |
| Apteka.ru | `apteka_ru` | requires_access | none | Pharmacy availability is region-specific and needs source approval. |
| M.Video | `mvideo` | requires_access | none | Stable public product data source is not approved. |
| Petrovich | `petrovich` | requires_access | none | Regional catalog stability requires source approval. |
| Magnit | `magnit` | requires_access | none | Grocery catalog depends on region/session data. |
| Lemana Pro | `lemana_pro` | requires_access | none | Regional catalog stability requires source approval. |

## Iteration 1 Checks

Completed on 2026-06-25:

- RED confirmed for missing `app.product_monitoring.registry`.
- RED confirmed for registry-backed Wildberries/Ozon URL normalization.
- `rtk python -m pytest app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py -q`:
  18 passed.
- `rtk python -m ruff check app/product_monitoring app/core/product_url_normalizer.py app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py`:
  passed.
- `rtk python -m ruff format --check app/product_monitoring app/core/product_url_normalizer.py app/tests/test_product_monitoring_registry.py app/tests/test_product_url_normalizer.py`:
  passed.
- `rtk python -m pytest app/tests/test_watchlist_api.py -q`: 23 passed, 1
  existing Starlette/httpx deprecation warning.
- Full backend `rtk python -m pytest -q`: 507 passed, 1 existing
  Starlette/httpx deprecation warning.
- During full-suite verification, time-dependent price-chart tests were fixed
  by freezing `app.services.price_chart.current_utc_datetime` in
  `test_price_chart_api.py`; runtime chart logic was not changed.

## 2026-06-25 Test Server Fix

The Wildberries add-item flow still returned `upstream_unavailable` after the
backend image was rebuilt because the test server did not have the FastAPI to
WordPress internal API configured. After enabling that channel, the remaining
root cause was the backend client encoding the WordPress external user id as
`wp%3A...%3A1`; WordPress treated the encoded value as invalid and returned
limits lookup errors, which caused watchlist creation to fall back to a zero
free limit.

Fix:

- `CashbackAPIClient.get_user_price_monitor_limits()` now keeps the safe
  `wp:host:user_id` path characters unescaped while still escaping unsafe path
  characters.
- The test server now has `savello_internal_api_enabled=1`,
  `CASHBACK_API_BASE_URL=http://nginx`, `CASHBACK_API_SITE_ID=savelloclub.ru`,
  and matching internal HMAC secrets configured without exposing secret values.

Verification:

- RED confirmed for the encoded `external_user_id` path.
- `rtk python -m pytest app/tests/test_cashback_api_client.py app/tests/test_user_limits_service.py app/tests/test_watchlist_api.py -q`:
  41 passed, 1 existing Starlette/httpx deprecation warning.
- Full backend `rtk python -m pytest -q`: 508 passed, 1 existing
  Starlette/httpx deprecation warning.
- `rtk python -m ruff check .`: passed.
- `rtk python -m ruff format --check .`: 174 files already formatted.

## Intentional Non-Goals

- No cart/favorites sync changes.
- No product search changes.
- No cross-store comparison changes.
- No marketplace session capture.
- No captcha bypass or anti-bot evasion.
- No paid proxy or scraping service integration.
