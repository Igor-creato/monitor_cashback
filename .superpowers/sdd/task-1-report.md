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
