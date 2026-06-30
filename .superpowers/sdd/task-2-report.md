# Task 2 Report: Backend Watchlist Limits, Duplicate Semantics, And Product Card Contract

## What You Implemented

- Added watchlist service support for:
  - unsupported source rejection via `SourceService.find_supported_source(...)`
  - active duplicate detection with stable error code `duplicate_watchlist_item`
  - per-user active watch limit enforcement with `max_tracked_products` defaulting to `10`
  - deleted watch re-add behavior by moving active uniqueness to `active_identity_key`
  - target price update support in `WatchlistService.update_target_price(...)`
- Extended `WatchlistItem` with `active_identity_key` and `updated_at`.
- Extended `Product` with card fields required by the product detail contract:
  - `image_url`
  - `rating_value`
  - `current_price_minor`
  - `currency`
  - `last_fetch_status`
  - `last_fetched_at`
  - `updated_at`
- Updated `POST /api/v1/watchlist/items` to:
  - apply max tracked product settings from admin settings
  - return stable error payloads for `unsupported_store`, `duplicate_watchlist_item`, `limit_exceeded`, and `invalid_target_price`
  - preserve HMAC + idempotency behavior
- Updated `GET /api/v1/watchlist/items` to require HMAC and `user_id`.
- Replaced placeholder `GET /api/v1/products/{product_id}` with the required signed product card contract.
- Updated the owned migration to add product card columns, add `active_identity_key` / `updated_at`, backfill existing rows, and replace the old `(user_id, canonical_url_hash)` uniqueness with active-row uniqueness.

## Commands And Results

Commit created: `184bf7d` (`feat: add watchlist limits and product card contract`)

1. `rtk python -m pytest tests/integration/test_watchlist_service.py -q`
   - RED: failed with `TypeError: WatchlistService.add_item() got an unexpected keyword argument 'max_tracked_products'`
2. `rtk python -m pytest tests/contract/test_product_card_contract.py -q`
   - RED: failed for the same missing `max_tracked_products` service capability before product card implementation
3. `rtk python -m pytest tests/contract/test_api_contract.py -q`
   - RED: `GET /api/v1/watchlist/items` and `GET /api/v1/products/{product_id}` returned `200` without HMAC
4. `rtk python -m pytest tests/integration/test_watchlist_service.py -q`
   - GREEN: `5 passed`
5. `rtk python -m pytest tests/contract/test_product_card_contract.py -q`
   - GREEN: `1 passed`
6. `rtk python -m pytest tests/contract/test_api_contract.py -q`
   - GREEN: `7 passed`
7. `rtk python -m pytest tests/integration/test_watchlist_service.py tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py tests/contract/test_admin_api_contract.py tests/unit/test_security.py -q`
   - GREEN: `20 passed`
8. `rtk git diff --check`
   - GREEN: no whitespace or patch-format issues

## TDD Evidence

### RED

- Watchlist behavior tests failed before implementation because `WatchlistService.add_item(...)` did not accept `max_tracked_products`.
- Product card contract failed before implementation because the same service capability was missing.
- API contract failed before router changes because watchlist list and product detail were readable without HMAC.

### GREEN

- Watchlist integration suite passed after service/model changes.
- Product card contract passed after product model and router changes.
- API contract and adjacent admin/security regressions passed after HMAC enforcement and stable error handling were added.

## Files Changed

- `tests/contract/test_product_card_contract.py`
- `tests/integration/test_watchlist_service.py`
- `tests/contract/test_api_contract.py`
- `src/price_monitor/domains/watchlist/models.py`
- `src/price_monitor/domains/watchlist/service.py`
- `src/price_monitor/domains/products/models.py`
- `src/price_monitor/api/v1/watchlist.py`
- `src/price_monitor/api/v1/products.py`
- `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`

## Self-Review Findings

- No unrelated files were modified.
- Existing `.claude-flow/` remained untouched.
- Product reuse still happens by `(source_domain, canonical_url_hash)`.
- Active duplicate semantics now apply only to active rows, which allows deleted rows to be re-added.
- Watchlist reads and product detail reads now follow the same signed-request posture as other WordPress-facing reads.

## Concerns / Deviations From Brief

- Preserved the current project’s keyword-only service call shape instead of changing call sites to positional dataclass-style examples from the brief.
- For the API surface, duplicate and limit errors are returned as explicit error responses with stable codes instead of the previous `200`/`created=false` duplicate behavior.
- `WatchlistService.update_target_price(...)` was implemented at the service layer because the brief listed the method contract, but Task 2 did not define a new router endpoint for it inside the owned scope.

## Task 2 Review 1

Reviewer found blocking issues requiring fixes:
- Negative target_price_minor is intercepted by request model validation and does not return stable invalid_target_price error payload.
- Supported subdomain URLs can create products with the URL hostname instead of the matched monitored source domain, causing product-card lookup to fail with source_not_found.

## Task 2 Review 1 Fix

### Scope

- Fixed only the two review-blocking issues:
  - stable `invalid_target_price` API semantics for `POST /api/v1/watchlist/items`
  - preserved matched monitored source identity for supported subdomain product-card resolution

### RED

1. Added `test_watchlist_create_rejects_negative_target_price_with_stable_error(...)` to `tests/contract/test_api_contract.py`.
2. Added `test_product_detail_resolves_supported_subdomain_to_monitored_source(...)` to `tests/contract/test_product_card_contract.py`.
3. Ran:
   - `rtk python -m pytest tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py -q`
4. Result:
   - `test_watchlist_create_rejects_negative_target_price_with_stable_error` failed because FastAPI returned generic validation payload under `detail` instead of stable `error.code=invalid_target_price`.
   - `test_product_detail_resolves_supported_subdomain_to_monitored_source` failed with `404` because product detail resolved `source_not_found` for a product added from `https://shop.example.com/...`.

### GREEN

1. Updated `src/price_monitor/api/v1/watchlist.py` so `target_price_minor` is no longer rejected by Pydantic range validation before route/service error mapping.
2. Updated `src/price_monitor/domains/watchlist/service.py` so `add_item(...)` keeps the matched `MonitoredSource.source_domain` and stores that identity on `Product.source_domain`.
3. Re-ran focused regressions:
   - `rtk python -m pytest tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py -q`
   - Result: `10 passed`
4. Ran required verification:
   - `rtk python -m pytest tests/integration/test_watchlist_service.py tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py -q`
     - Result: `15 passed`
   - `rtk python -m pytest tests/contract/test_admin_api_contract.py tests/unit/test_security.py -q`
     - Result: `7 passed`
   - `rtk python -m ruff check src/price_monitor/api/v1/watchlist.py src/price_monitor/api/v1/products.py src/price_monitor/domains/watchlist/service.py tests/integration/test_watchlist_service.py tests/contract/test_product_card_contract.py tests/contract/test_api_contract.py`
     - Result: `All checks passed!`

### Files Changed

- `tests/contract/test_api_contract.py`
- `tests/contract/test_product_card_contract.py`
- `src/price_monitor/api/v1/watchlist.py`
- `src/price_monitor/domains/watchlist/service.py`

### Self-Review

- `invalid_target_price` now comes from the stable route/service error mapping instead of framework-level validation output.
- Supported subdomain URLs still match configured monitored sources, and products created from those URLs now retain the monitored source identity required by product-card lookup.
- No migration, model, or `.claude-flow/` changes were needed for these fixes.


## Task 2 Review 2

Reviewer found one remaining Important issue:
- DELETE /api/v1/watchlist/items/{item_id} only checks Idempotency-Key presence but does not reserve/complete idempotency state. Mutating backend endpoints require real HMAC and idempotency semantics.

## Task 2 Review 2 Fix

### Scope

- Fixed only the remaining Important DELETE idempotency issue.
- Kept the change scoped to the watchlist DELETE endpoint, its contract tests, and the minimal helper behavior needed to replay a completed `204` response.

### RED

1. Added `test_watchlist_delete_replays_completed_idempotent_response(...)` to `tests/contract/test_api_contract.py`.
2. Added `test_watchlist_delete_rejects_same_idempotency_key_for_different_target(...)` to `tests/contract/test_api_contract.py`.
3. Ran:
   - `rtk python -m pytest tests/contract/test_api_contract.py -k "watchlist_delete" -q`
4. Result:
   - `test_watchlist_delete_replays_completed_idempotent_response` failed because DELETE never created or completed an idempotency record.
   - `test_watchlist_delete_rejects_same_idempotency_key_for_different_target` failed because reusing the same key against a different `item_id` returned `204` instead of `409 idempotency_conflict`.

### GREEN

1. Updated `src/price_monitor/api/v1/watchlist.py` so DELETE now:
   - reserves/completes an idempotency record;
   - replays a completed `204` safely for the same key and target;
   - hashes `item_id` into the delete request identity so same-key/different-target reuse conflicts.
2. Updated `src/price_monitor/core/idempotency.py` so completed records with an empty JSON body (`{}`) still replay correctly.
3. Re-ran focused regressions:
   - `rtk python -m pytest tests/contract/test_api_contract.py -k "watchlist_delete" -q`
   - Result: `2 passed`
4. Ran required verification:
   - `rtk python -m pytest tests/contract/test_api_contract.py tests/integration/test_watchlist_service.py -q`
     - Result: `15 passed`
   - `rtk python -m pytest tests/contract/test_product_card_contract.py tests/contract/test_admin_api_contract.py tests/unit/test_security.py -q`
     - Result: `9 passed`
   - `rtk python -m ruff check src/price_monitor/api/v1/watchlist.py tests/contract/test_api_contract.py tests/integration/test_watchlist_service.py src/price_monitor/core/idempotency.py`
     - Result: `All checks passed!`
   - `rtk git diff --check`
     - Result: no whitespace or patch-format issues

### Files Changed

- `tests/contract/test_api_contract.py`
- `src/price_monitor/api/v1/watchlist.py`
- `src/price_monitor/core/idempotency.py`

### Self-Review

- DELETE now matches the existing mutating-endpoint pattern: require HMAC, reserve idempotency state before mutation, and complete it with the final response.
- Repeating the same DELETE with the same `Idempotency-Key` replays the original `204` and does not emit a second delete outbox event.
- Reusing the same key against a different delete target now fails closed with `idempotency_conflict`.
- Product rows and price history remain untouched; delete still only deactivates the watch by clearing the active identity key.

