# Task 4 Report: Watchlist Rejects Non-Product URLs Before Product Creation

## Outcome

Implemented the watchlist guard so required-store non-product URLs are rejected before any `Product` row is created. Generic admin-configured sources still use the existing domain-based watchlist flow.

## RED

Added `tests/integration/test_watchlist_service.py::test_add_item_rejects_supported_store_non_product_url`.

Verified the failure:

```text
AssertionError: assert <price_monitor.domains.watchlist.models.WatchlistItem object ...> is None
```

That showed `WatchlistService.add_item()` was still accepting a supported store category URL and creating a product/item pair.

## GREEN

Made the minimal backend changes:

- Added `source_product_id` to `Product` as a nullable indexed column in `src/price_monitor/domains/products/models.py`
- Added required-store classification in `src/price_monitor/domains/watchlist/service.py`
- Rejected `not_product_url` before duplicate checks for required-store domains
- Passed `classification.source_product_id` into product creation
- Updated `src/price_monitor/api/v1/watchlist.py` to return the stable `not_product_url` API error payload
- Added the contract test `tests/contract/test_api_contract.py::test_watchlist_create_rejects_non_product_required_store_url`

## Files Changed

- `src/price_monitor/domains/products/models.py`
- `src/price_monitor/domains/watchlist/service.py`
- `src/price_monitor/api/v1/watchlist.py`
- `tests/integration/test_watchlist_service.py`
- `tests/contract/test_api_contract.py`

## Behavior Delivered

- Supported-store category/search URLs are rejected in watchlist creation with `not_product_url`
- Rejection happens before duplicate checks and before product creation
- Generic configured sources such as `example.com` still follow the existing domain-based watchlist path
- `Product.source_product_id` is available for store-backed product rows and remains nullable, so no migration was needed for the test DB setup

## Verification

Targeted red/green:

```text
rtk py -m pytest tests/integration/test_watchlist_service.py::test_add_item_rejects_supported_store_non_product_url -q
FAIL
```

Green checks:

```text
rtk py -m pytest tests/integration/test_watchlist_service.py::test_add_item_rejects_supported_store_non_product_url tests/contract/test_api_contract.py::test_watchlist_create_rejects_non_product_required_store_url -q
2 passed
rtk py -m pytest tests/integration/test_watchlist_service.py tests/contract/test_api_contract.py -q
25 passed
rtk py -m pytest tests/unit/test_product_url_classifier.py -q
20 passed
rtk git diff --check
clean
```

## Concerns

- No migration was added, by design; `source_product_id` is nullable so the existing metadata-created test DB pattern keeps working.
- The watchlist API now exposes `not_product_url`, which is consistent with the sources classifier and keeps the contract stable.

## Commit

- `8f1ee78f38b437725225b6d74f5df079031a69f5` - `feat: reject non-product watchlist urls`
