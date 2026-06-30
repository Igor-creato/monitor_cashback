# Task 4 Report

## What you implemented
- Added `AlertEvent` persistence for desired-price threshold crossings with dedup key `price-target:{watchlist_item_id}:{target_price_minor}:{observed_price_minor}` and pending status.
- Added `NotificationService.evaluate_product(product_id: str, now: datetime) -> list[AlertEvent]` to evaluate active watchlist items, create `AlertEvent`, and enqueue one `OutboxEvent` with event type `notification.price_target_reached`.
- Registered `AlertEvent` in SQLAlchemy metadata and extended `20260630_0002_price_monitor_vertical_slice.py` to create/drop the `alert_events` table plus supporting indexes.
- Wired `NotificationService` into `FetchPipeline.run()` after the product update and `PricePoint` insert so below-target fetches emit one pending alert event.

## Commands and results
- `rtk python -m pytest tests/unit/test_notification_service.py -q`
  - RED: `ModuleNotFoundError: No module named 'price_monitor.domains.notifications.service'`
  - GREEN after implementation: `1 passed`
- `rtk python -m pytest tests/unit/test_fetch_pipeline.py -q`
  - RED after adding the pipeline regression: `FAILED ... assert 0 == 1` in `test_fetch_pipeline_creates_pending_alert_event_when_price_crosses_target`
- `rtk python -m pytest tests/unit/test_fetch_pipeline.py tests/unit/test_notification_service.py -q`
  - GREEN: `9 passed`
- `rtk python -m pytest tests/unit/test_reliability.py -q`
  - GREEN: `2 passed`
- `rtk ruff check src/price_monitor/domains/notifications/service.py src/price_monitor/domains/reliability/models.py src/price_monitor/db/models.py src/price_monitor/domains/fetching/service.py tests/unit/test_notification_service.py tests/unit/test_fetch_pipeline.py migrations/versions/20260630_0002_price_monitor_vertical_slice.py`
  - GREEN: `No issues found`
- `rtk powershell -NoProfile -Command 'New-Item -ItemType Directory -Force ''.tmp'' | Out-Null; $env:PRICE_MONITOR_DATABASE_URL=''sqlite+pysqlite:///./.tmp/task4-alembic.db''; rtk alembic upgrade head'`
  - GREEN: upgraded through `20260630_0002`
- `rtk git diff --check`
  - GREEN: no output
- `rtk git commit -m "feat: add desired price alert events"`
  - GREEN: commit created `eb9801ab365f3d26dd1befea23c14a69b0eb53db`

## TDD RED/GREEN evidence
- Notification service test was written first and failed on the missing service import before any production code existed.
- Fetch pipeline regression test was added after the service slice went green and failed because no `AlertEvent` was created from `FetchPipeline.run()`.
- After wiring `NotificationService.evaluate_product()` into the fetch pipeline, the focused task suite passed.

## Files changed
- `src/price_monitor/domains/notifications/service.py`
- `tests/unit/test_notification_service.py`
- `src/price_monitor/domains/reliability/models.py`
- `src/price_monitor/db/models.py`
- `src/price_monitor/domains/fetching/service.py`
- `tests/unit/test_fetch_pipeline.py`
- `migrations/versions/20260630_0002_price_monitor_vertical_slice.py`

## Self-review findings
- No functional issues found in self-review for the scoped Task 4 contract.
- The outbox event is intentionally backend-owned and dispatch-ready; no WordPress delivery endpoint or browser-facing mutation surface was added here.
- Test output still shows the pre-existing `StarletteDeprecationWarning` from `fastapi.testclient`; this task did not change that behavior.

## Concerns/deviations from brief
- None.

## Task 4 Review 1

Reviewer found blocking issues requiring fixes:
- NotificationService dedup path is read-then-insert and can raise IntegrityError under concurrent threshold evaluations instead of harmlessly returning no duplicate event.
- Tests do not cover explicit skip gates: inactive watchlist items, null target_price_minor, null product current_price_minor, and current price above target.

## Task 4 Review 1 Fix

### What changed
- Hardened `NotificationService` alert creation by moving `AlertEvent` + `OutboxEvent` writes into a nested transaction/savepoint and catching `IntegrityError` so duplicate concurrent evaluations return `[]` instead of poisoning the outer session.
- Kept the existing contract unchanged: outbox event type stays `notification.price_target_reached` and dedup key stays `price-target:{watchlist_item_id}:{target_price_minor}:{observed_price_minor}`.
- Added explicit unit coverage for the four skip gates from the brief: inactive watchlist item, null `target_price_minor`, null `product.current_price_minor`, and `current_price_minor > target_price_minor`.
- Added a focused race regression test that forces unique-key `IntegrityError` at both alert and outbox flush points and verifies `evaluate_product()` returns `[]` while the outer transaction still commits.

### RED/GREEN evidence
- `rtk python -m pytest tests/unit/test_notification_service.py -q`
  - RED after adding the new tests: duplicate-race cases raised `IntegrityError` out of `NotificationService.evaluate_product()`.
  - Note: the first RED pass also showed skip-gate assertion noise because watchlist setup creates unrelated outbox rows; the assertions were tightened to filter only `notification.price_target_reached`, then rerun.
  - Expected RED after tightening the assertions: `2 failed, 5 passed`, with both failures on duplicate-race handling.
- `rtk python -m pytest tests/unit/test_notification_service.py -q`
  - GREEN after the service fix: `7 passed`

### Verification commands and results
- `rtk python -m pytest tests/unit/test_fetch_pipeline.py tests/unit/test_reliability.py -q`
  - GREEN: `10 passed`
- `rtk python -m ruff check src/price_monitor/domains/notifications/service.py tests/unit/test_notification_service.py`
  - GREEN: `All checks passed!`
- `rtk git diff --check`
  - GREEN before commit: no output

### Files changed
- `src/price_monitor/domains/notifications/service.py`
- `tests/unit/test_notification_service.py`

### Self-review
- The dedup race is now handled at the write boundary instead of by read-before-write assumptions, so concurrent duplicate threshold evaluations fall back to the intended no-op behavior.
- The outer transaction remains usable after a duplicate race; the regression test commits an unrelated product update after `evaluate_product()` returns `[]`.
- No fetch-pipeline behavior, outbox event type, dedup key format, or WordPress delivery surface was expanded beyond the review blockers.

