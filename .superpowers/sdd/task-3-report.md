# Task 3 Report: Backend Price Chart And Fetch Pipeline With Fake Adapters

## What I implemented

- Added the new fetching domain in `src/price_monitor/domains/fetching/`:
  - `ports.py` for `FetchedProductData`, `FetchPageResult`, and `ProductPageFetcher`
  - `extraction.py` for JSON-LD `Product` extraction with `@graph`, list roots, `offers.price` / `offers.lowPrice`, image normalization, and decimal-to-minor conversion
  - `service.py` for `FetchPipeline`, `ProductFetchResult`, and chart summarization
  - `__init__.py` exports
- Added fetch-attempt persistence in `src/price_monitor/domains/reliability/models.py` via `FetchAttempt`.
- Linked price samples to attempts in `src/price_monitor/domains/pricing/models.py` via `PricePoint.fetch_attempt_id`.
- Registered the new model in `src/price_monitor/db/models.py`.
- Extended `src/price_monitor/api/v1/price_history.py`:
  - `price-history` now requires signed WordPress requests
  - added `GET /api/v1/products/{product_id}/price-chart`
- Wired `src/price_monitor/workers/tasks/fetch_product.py` to open a DB session, run `FetchPipeline`, and return the pipeline status.
- Extended `migrations/versions/20260630_0002_price_monitor_vertical_slice.py` with:
  - `fetch_attempts`
  - `price_points.fetch_attempt_id`
- Added new task tests:
  - `tests/unit/test_fetch_extraction.py`
  - `tests/unit/test_fetch_pipeline.py`
- Updated `tests/contract/test_api_contract.py` because Task 3 intentionally changes the `price-history` read contract to require HMAC.

## Commands and results

1. `rtk python -m pytest tests/unit/test_fetch_extraction.py -q`
   - RED: `ModuleNotFoundError: No module named 'price_monitor.domains.fetching'`
2. `rtk python -m pytest tests/unit/test_fetch_extraction.py -q`
   - GREEN: `3 passed`
3. `rtk python -m pytest tests/unit/test_fetch_pipeline.py -q`
   - RED: `ModuleNotFoundError: No module named 'price_monitor.domains.fetching.service'`
4. `rtk python -m pytest tests/unit/test_fetch_extraction.py tests/unit/test_fetch_pipeline.py -q`
   - GREEN: `8 passed`
5. `rtk python -m pytest tests/unit/test_fetch_extraction.py tests/unit/test_fetch_pipeline.py tests/contract/test_product_card_contract.py tests/unit/test_ports_and_worker_config.py -q`
   - GREEN: `13 passed`
6. `rtk python -m pytest tests/contract/test_api_contract.py -q`
   - Initial adjacent failure: old unauthenticated `price-history` expectation
   - After contract update: GREEN `12 passed`
7. `rtk git diff --check`
   - GREEN: no whitespace or conflict-marker issues
8. `rtk python -m pytest tests/unit/test_fetch_extraction.py tests/unit/test_fetch_pipeline.py tests/contract/test_product_card_contract.py tests/unit/test_ports_and_worker_config.py tests/contract/test_api_contract.py -q`
   - GREEN: `25 passed`

## TDD RED/GREEN evidence

- Extraction seam:
  - RED on missing fetching package
  - GREEN after minimal ports/extraction implementation
- Pipeline seam:
  - RED on missing `FetchPipeline`
  - GREEN after minimal fetch pipeline/model/API/worker wiring
- Adjacent contract seam:
  - Existing read-only API contract failed because Task 3 changes `price-history` authentication
  - GREEN after updating the contract to signed-read behavior

## Files changed

- Created: `src/price_monitor/domains/fetching/__init__.py`
- Created: `src/price_monitor/domains/fetching/ports.py`
- Created: `src/price_monitor/domains/fetching/extraction.py`
- Created: `src/price_monitor/domains/fetching/service.py`
- Created: `tests/unit/test_fetch_extraction.py`
- Created: `tests/unit/test_fetch_pipeline.py`
- Modified: `src/price_monitor/domains/reliability/models.py`
- Modified: `src/price_monitor/domains/pricing/models.py`
- Modified: `src/price_monitor/api/v1/price_history.py`
- Modified: `src/price_monitor/workers/tasks/fetch_product.py`
- Modified: `src/price_monitor/db/models.py`
- Modified: `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`
- Modified: `tests/contract/test_api_contract.py`
- Created: `.superpowers/sdd/task-3-report.md`

## Self-review findings

- No functional blockers found in the implemented Task 3 scope.
- The one scope expansion was intentional and minimal: `tests/contract/test_api_contract.py` needed an HMAC update because Task 3 explicitly changes the `price-history` contract.
- `.claude-flow/` was left untouched.
- No real browser automation, anti-bot, captcha-bypass, raw-cookie, or password storage logic was introduced.

## Concerns/deviations from brief

- The brief's requested commit message is `feat: add fetch pipeline and price chart`; I will use that exact message.
- One adjacent contract test outside the initial ownership list had to be updated to match the new signed-read requirement for `price-history`.
- Existing warnings remain in adjacent tests:
  - `fastapi.testclient` / `httpx` deprecation warning
  - existing watchlist `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning
