# Task 1 Report: Backend Monitored Sources, Settings, And Admin API

## What I implemented

- Added monitored-source, monitor-setting, proxy-pool, and proxy-endpoint SQLAlchemy models in `src/price_monitor/domains/sources/models.py`.
- Added `SourceService` in `src/price_monitor/domains/sources/service.py` with:
  - `upsert_source(payload: MonitoredSourceInput) -> MonitoredSource`
  - `find_supported_source(raw_url: str) -> MonitoredSource | None`
  - source listing
  - monitor settings read/update helpers
- Added source/admin schemas in `src/price_monitor/domains/sources/schemas.py`.
- Added `POST /api/v1/admin/sources`, `GET /api/v1/admin/sources`, `PATCH /api/v1/admin/settings`, and `GET /api/v1/admin/settings` in `src/price_monitor/api/v1/admin.py`.
- Added signed `GET /api/v1/sources/supported?url=...` in `src/price_monitor/api/v1/sources.py`.
- Registered the admin router in `src/price_monitor/main.py`.
- Registered the new models in `src/price_monitor/db/models.py`.
- Added Alembic migration `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`.
- Added RED->GREEN tests in:
  - `tests/unit/test_source_service.py`
  - `tests/contract/test_admin_api_contract.py`

## TDD evidence

### Source service RED

Command:

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
```

Result:

```text
ERROR collecting tests/unit/test_source_service.py
ModuleNotFoundError: No module named 'price_monitor.domains.sources.service'
```

This was the expected missing-service failure.

### Source service GREEN

Command:

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
```

Result:

```text
.. [100%]
```

### Admin API RED

Command:

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
```

Result:

```text
FAILED tests/contract/test_admin_api_contract.py::test_admin_source_and_settings_contract
assert 404 == 201
```

Captured requests showed `404 Not Found` for:

- `POST /api/v1/admin/sources`
- `GET /api/v1/admin/sources`
- `GET /api/v1/sources/supported`
- `PATCH /api/v1/admin/settings`
- `GET /api/v1/admin/settings`

This was the expected missing-route failure.

### Admin API GREEN

Command:

```powershell
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
```

Result:

```text
... [100%]
```

## Commands and results

1. Pattern inspection and scope checks

```powershell
rtk git status --short --branch
rtk git rev-parse --short HEAD
rtk rg --files
rtk rg -n "verify_wordpress_request|Idempotency-Key|idempotency|verify_.*request|x-signature|x-timestamp|processed_messages" src tests
```

Results:

- branch confirmed as `feature/price-monitor-service`
- base commit confirmed as `f07e31e`
- existing HMAC/idempotency pattern confirmed in `watchlist.py`, `api/dependencies.py`, `core/security.py`, and `core/idempotency.py`

2. Focused Task 1 RED/GREEN runs

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
```

Results:

- first command RED with missing `price_monitor.domains.sources.service`
- second command RED with `404` on missing admin/supported routes
- combined command GREEN

3. Related regression and hygiene checks

```powershell
rtk python -m pytest tests/contract/test_api_contract.py tests/integration/test_watchlist_service.py -q
rtk python -m ruff check src tests migrations
rtk git diff --check
```

Results:

- regression tests GREEN: `....... [100%]`
- Ruff GREEN after import/format cleanup: `All checks passed!`
- `git diff --check` returned clean output

4. Migration smoke

```powershell
rtk powershell -NoProfile -Command '$env:PRICE_MONITOR_DATABASE_URL="sqlite:///migration-smoke.db"; rtk alembic upgrade head'
rtk powershell -NoProfile -Command "Remove-Item -LiteralPath 'F:\cash-back\monitor_cashback\migration-smoke.db'"
```

Results:

- Alembic upgraded `20260629_0001 -> 20260630_0002` successfully on SQLite
- temporary smoke database removed

5. Final pre-commit verification

```powershell
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py tests/contract/test_api_contract.py tests/integration/test_watchlist_service.py -q
rtk python -m ruff check src tests migrations
rtk git diff --check
```

Results:

- `.......... [100%]`
- `All checks passed!`
- clean diff check

## Files changed

- `src/price_monitor/api/v1/admin.py`
- `src/price_monitor/api/v1/sources.py`
- `src/price_monitor/main.py`
- `src/price_monitor/db/models.py`
- `src/price_monitor/domains/sources/models.py`
- `src/price_monitor/domains/sources/service.py`
- `src/price_monitor/domains/sources/schemas.py`
- `tests/unit/test_source_service.py`
- `tests/contract/test_admin_api_contract.py`
- `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`
- `.superpowers/sdd/task-1-report.md`

## Self-review findings

- No blocking issues found in the Task 1 slice after the final verification pass.
- Admin mutations mirror the existing watchlist HMAC/idempotency pattern and persist replay payloads as JSON-safe dicts.
- The supported-source lookup is fail-closed on unsupported domains and keeps the existing URL validation path through `validate_public_product_url()`.
- Existing watchlist/API regression tests still pass after router/model registration changes.
- The migration applies cleanly against a SQLite smoke database.

## Concerns or deviations from the brief

- I used an existing thin-router/service/schema pattern from this repo even where the brief only prescribed endpoint names. That preserved local conventions without changing the requested behavior.
- `monitor_settings` is implemented as a simple key-value table and the HTTP schema currently exposes only `max_tracked_products_per_user`, which is the single setting exercised by this Task 1 slice.
- Added `status` indexes for `proxy_pools` and `proxy_endpoints` alongside the required `status`, `pool_id`, and `tier` indexing because that matches the same query/index style already used elsewhere in the repo.

## Commit

- commit message: `feat: add monitored source admin api`
- exact short SHA: see current `HEAD` with `rtk git log -1 --oneline`

## Task 1 Review 1

Reviewer found Important issues requiring fixes:
- GET /api/v1/sources/supported must bind its url query input into the signature or otherwise reject mismatched signed input.
- Admin source validation must reject invalid status/ranges/blank or overly broad domains without 500s and without weakening unsupported_store matching.

## Task 1 Review 1 Fix

### Scope

- Fixed only the two Important review findings from round 1.
- Left the existing body-based HMAC contract for mutating endpoints unchanged.
- Left unrelated untracked `.claude-flow/` untouched.

### RED -> GREEN evidence

#### RED: new unit test for broad monitored-source domains

Command:

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
```

Result:

```text
ImportError: cannot import name 'InvalidMonitoredSourceError' from 'price_monitor.domains.sources.service'
```

This was the expected RED showing the new service-level validation path did not exist yet.

#### RED: new contract coverage for signed GET query binding and invalid admin payloads

Command:

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
```

Result:

```text
FAILED test_admin_source_and_settings_contract
TypeError: build_signed_headers() got an unexpected keyword argument 'query'

FAILED test_supported_source_signature_cannot_be_reused_for_different_url
TypeError: build_signed_headers() got an unexpected keyword argument 'query'

FAILED test_admin_source_contract_rejects_invalid_payloads
ValueError: status is invalid
```

This proved both review findings before any production fix:

- GET signing could not bind query input yet.
- Invalid admin payloads still escaped as uncaught service `ValueError`.

#### GREEN: focused review-fix tests

Commands:

```powershell
rtk python -m pytest tests/unit/test_source_service.py -q
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
```

Results:

```text
... [100%]
... [100%]
...... [100%]
```

### Implementation summary

- Added query-aware canonical request-target signing in `src/price_monitor/core/security.py` and bound GET query strings in `src/price_monitor/api/dependencies.py`, so `GET /api/v1/sources/supported?url=...` now authenticates the signed `url` input.
- Kept the existing path+body signing contract for body-based mutating requests by signing query input only for GET verification.
- Added shared monitored-source domain validation in `src/price_monitor/domains/sources/service.py` with rejection for blank, malformed, scheme/path-bearing, and public-suffix-like broad domains such as `com` and `co.uk`.
- Added schema validation in `src/price_monitor/domains/sources/schemas.py` for normalized source status and domain input.
- Added admin fallback handling in `src/price_monitor/api/v1/admin.py` so service-side monitored-source validation errors return a client error instead of a 500.

### Commands and results

1. Required focused verification

```powershell
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
```

Result:

```text
...... [100%]
```

2. Required lint

```powershell
rtk python -m ruff check src/price_monitor/api/v1/admin.py src/price_monitor/api/v1/sources.py src/price_monitor/api/dependencies.py src/price_monitor/core/security.py src/price_monitor/domains/sources tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py
```

Result:

```text
All checks passed!
```

3. Required diff hygiene

```powershell
rtk git diff --check
```

Result:

```text
clean output
```

### Files changed for the fix

- `src/price_monitor/api/v1/admin.py`
- `src/price_monitor/api/dependencies.py`
- `src/price_monitor/core/security.py`
- `src/price_monitor/domains/sources/schemas.py`
- `src/price_monitor/domains/sources/service.py`
- `tests/unit/test_source_service.py`
- `tests/contract/test_admin_api_contract.py`
- `.superpowers/sdd/task-1-report.md`

### Self-review

- The new supported-source contract test now proves a signature generated for `https://example.com/p/1` is rejected when replayed against a different `url` query value.
- Existing mutating request signing still uses the same canonical path/body inputs as before.
- Broad monitored-source domains are now rejected both at the API boundary and inside `SourceService`, so unsupported-store matching cannot be widened by storing `com`/`co.uk`.
- I did not touch migrations or models for this repair because the review findings were confined to request signing and validation behavior.

## Task 1 Review 2

Reviewer found one remaining Important issue:
- Query signature binding remains bypassable with duplicate url params because canonicalization sorts query pairs while FastAPI scalar url consumption is order-sensitive. Add RED regression for url=a&url=b versus url=b&url=a and fix by rejecting duplicate url params or signing exact raw query input.

## Task 1 Review 2 Fix

### Scope

- Fixed exactly the remaining duplicate-`url` query-signature bypass on `GET /api/v1/sources/supported`.
- Preserved the existing body-based signing behavior for mutating endpoints.
- Left unrelated untracked `.claude-flow/` untouched.

### RED -> GREEN evidence

#### RED: duplicate `url` query ordering replay still passed

Command:

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
```

Result:

```text
FAILED tests/contract/test_admin_api_contract.py::test_supported_source_rejects_duplicate_url_query_params
assert 200 == 422
```

This proved the remaining review finding before the production fix:

- a signature minted for one raw duplicate-`url` ordering was accepted for the reversed ordering
- FastAPI still resolved the scalar `url` input from that reordered duplicate query and returned `200 OK`

#### GREEN: duplicate `url` query params are now rejected

Commands:

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
```

Results:

```text
.... [100%]
....... [100%]
```

### Implementation summary

- Added a contract regression in `tests/contract/test_admin_api_contract.py` that signs one duplicate-`url` raw query ordering and replays the same signature against the reversed ordering.
- Updated `src/price_monitor/api/v1/sources.py` to reject requests containing anything other than exactly one `url` query param with `422`, preventing order-sensitive scalar binding from changing the effective supported-source lookup target.
- Did not change `src/price_monitor/core/security.py` or `src/price_monitor/api/dependencies.py` because the endpoint-level rejection fully closes the remaining supported-source bypass without altering the current mutating-request signing contract.

### Commands and results

1. Required RED proof

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
```

Result:

```text
FAILED tests/contract/test_admin_api_contract.py::test_supported_source_rejects_duplicate_url_query_params
assert 200 == 422
```

2. Required verification

```powershell
rtk python -m pytest tests/contract/test_admin_api_contract.py -q
rtk python -m pytest tests/unit/test_source_service.py tests/contract/test_admin_api_contract.py -q
rtk python -m ruff check src/price_monitor/api/dependencies.py src/price_monitor/api/v1/sources.py src/price_monitor/core/security.py tests/contract/test_admin_api_contract.py
rtk git diff --check
```

Results:

```text
.... [100%]
....... [100%]
All checks passed!
clean output
```

### Files changed for the fix

- `src/price_monitor/api/v1/sources.py`
- `tests/contract/test_admin_api_contract.py`
- `.superpowers/sdd/task-1-report.md`

### Self-review

- The new regression proves duplicate `url` params cannot be used to replay one valid signature against a different effective supported-source lookup target.
- The fix is narrowly scoped to the only endpoint that currently binds signed GET query input into a scalar `url` parameter.
- Existing body-based mutating signing behavior remains unchanged.
