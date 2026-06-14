from __future__ import annotations

import importlib
import logging
import sys

import pytest


def _reload_celery_modules(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RABBITMQ_URL", "amqp://unit-test-broker//")
    for module_name in (
        "app.tasks.periodic",
        "app.tasks.http_fetch",
        "app.tasks",
        "app.celery_app",
        "app.core.config",
    ):
        sys.modules.pop(module_name, None)
    return importlib.import_module("app.celery_app")


def test_periodic_tasks_are_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    celery_module = _reload_celery_modules(monkeypatch)

    assert (
        "app.tasks.periodic.schedule_due_fetch_jobs_task"
        in celery_module.celery_app.tasks
    )
    assert "app.tasks.periodic.cleanup_old_data_task" in celery_module.celery_app.tasks
    assert (
        "app.tasks.periodic.refresh_source_quarantine_task"
        in celery_module.celery_app.tasks
    )


def test_beat_schedule_contains_scheduler_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    celery_module = _reload_celery_modules(monkeypatch)

    schedule = celery_module.celery_app.conf.beat_schedule

    assert schedule["schedule-due-fetch-jobs"]["task"] == (
        "app.tasks.periodic.schedule_due_fetch_jobs_task"
    )
    assert schedule["schedule-due-fetch-jobs"]["schedule"] == 300


def test_scheduler_task_calls_service_with_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_celery_modules(monkeypatch)
    task_module = importlib.import_module("app.tasks.periodic")
    calls: list[int] = []

    def fake_schedule_due_fetch_jobs(limit: int) -> str:
        calls.append(limit)
        return "scheduled"

    monkeypatch.setattr(
        task_module,
        "schedule_due_fetch_jobs",
        fake_schedule_due_fetch_jobs,
    )

    result = task_module.schedule_due_fetch_jobs_task.run()

    assert result == "scheduled"
    assert calls == [100]


def test_cleanup_task_calls_all_cleanup_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_celery_modules(monkeypatch)
    task_module = importlib.import_module("app.tasks.periodic")
    calls: list[tuple[str, int]] = []

    def fake_cleanup_price_history(retention_days: int) -> int:
        calls.append(("price_history", retention_days))
        return 1

    def fake_cleanup_old_fetch_jobs(retention_days: int) -> int:
        calls.append(("fetch_jobs", retention_days))
        return 2

    def fake_cleanup_notification_events(retention_days: int) -> int:
        calls.append(("notification_events", retention_days))
        return 3

    monkeypatch.setattr(
        task_module,
        "cleanup_price_history",
        fake_cleanup_price_history,
    )
    monkeypatch.setattr(
        task_module,
        "cleanup_old_fetch_jobs",
        fake_cleanup_old_fetch_jobs,
    )
    monkeypatch.setattr(
        task_module,
        "cleanup_notification_events",
        fake_cleanup_notification_events,
    )

    result = task_module.cleanup_old_data_task.run()

    assert result == {
        "price_history_deleted": 1,
        "fetch_jobs_deleted": 2,
        "notification_events_deleted": 3,
    }
    assert calls == [
        ("price_history", 30),
        ("fetch_jobs", 30),
        ("notification_events", 30),
    ]


def test_quarantine_refresh_task_calls_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_celery_modules(monkeypatch)
    task_module = importlib.import_module("app.tasks.periodic")
    calls = 0

    def fake_refresh_source_quarantine_states() -> int:
        nonlocal calls
        calls += 1
        return 4

    monkeypatch.setattr(
        task_module,
        "refresh_source_quarantine_states",
        fake_refresh_source_quarantine_states,
    )

    result = task_module.refresh_source_quarantine_task.run()

    assert result == 4
    assert calls == 1


def test_task_logs_and_reraises_service_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _reload_celery_modules(monkeypatch)
    task_module = importlib.import_module("app.tasks.periodic")

    def fake_schedule_due_fetch_jobs(limit: int) -> None:
        raise RuntimeError(f"boom-{limit}")

    monkeypatch.setattr(
        task_module,
        "schedule_due_fetch_jobs",
        fake_schedule_due_fetch_jobs,
    )

    with caplog.at_level(logging.ERROR, logger=task_module.__name__):
        with pytest.raises(RuntimeError, match="boom-100"):
            task_module.schedule_due_fetch_jobs_task.run()

    assert "schedule_due_fetch_jobs_task_failed" in caplog.text
