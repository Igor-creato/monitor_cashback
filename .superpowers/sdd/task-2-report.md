# Task 2 Report: Due Fetch Scheduler Uses Effective Interval

## Outcome

Implemented `schedule_due_fetch_jobs(session, *, now, limit=100) -> list[FetchJob]` in `src/price_monitor/workers/scheduler.py`.
The scheduler now uses `SourceService.effective_fetch_interval_hours(source)` so:

- a source with `fetch_interval_hours = 0` falls back to the global `price_refresh_interval_hours`
- an explicit per-source `fetch_interval_hours` override is preserved

## RED

Created `tests/unit/test_fetch_scheduler.py` with the first failing import-based behavior test.

Verified failure:

```text
ModuleNotFoundError: No module named 'price_monitor.workers.scheduler'
```

## GREEN

Added `src/price_monitor/workers/scheduler.py` with the due-job scan and interval check.
Added a second unit test covering the explicit source override path.

Verification:

```text
py -m pytest tests/unit/test_fetch_scheduler.py -q
.. [100%]
```

Broader verification:

```text
py -m pytest tests/unit/test_fetch_scheduler.py tests/unit/test_source_service.py tests/integration/test_watchlist_service.py -q
................ [100%]
```

Also ran:

```text
git diff --check
```

## Files Changed

- `src/price_monitor/workers/scheduler.py`
- `tests/unit/test_fetch_scheduler.py`

## Self-Review

- Scheduler logic is minimal and calls the existing source-service interval helper directly.
- The implementation keeps the backend change scoped to the new worker module and its tests.
- I intentionally did not modify `src/price_monitor/domains/watchlist/service.py`; the existing watchlist service behavior stayed correct for this task.

## Concerns

None noted from the targeted test set.

## Commit

- `b24b19c` `feat: schedule due price refresh jobs`
