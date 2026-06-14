from __future__ import annotations

import importlib
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


def test_celery_app_reads_broker_url_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    celery_module = _reload_celery_modules(monkeypatch)

    assert celery_module.celery_app.conf.broker_url == "amqp://unit-test-broker//"


def test_http_fetch_task_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    celery_module = _reload_celery_modules(monkeypatch)

    assert "app.tasks.http_fetch.http_fetch_job" in celery_module.celery_app.tasks


def test_http_fetch_task_calls_runner_with_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_celery_modules(monkeypatch)
    task_module = importlib.import_module("app.tasks.http_fetch")
    calls: list[tuple[int, object]] = []

    class FakeFetcher:
        pass

    def fake_run_http_fetch_job(job_id: int, fetcher: object) -> str:
        calls.append((job_id, fetcher))
        return "ok"

    monkeypatch.setattr(task_module, "HTTPPriceFetcher", FakeFetcher)
    monkeypatch.setattr(task_module, "run_http_fetch_job", fake_run_http_fetch_job)

    result = task_module.http_fetch_job.run(123)

    assert result == "ok"
    assert len(calls) == 1
    assert calls[0][0] == 123
    assert isinstance(calls[0][1], FakeFetcher)


def test_http_fetch_task_does_not_swallow_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_celery_modules(monkeypatch)
    task_module = importlib.import_module("app.tasks.http_fetch")

    class FakeFetcher:
        pass

    def fake_run_http_fetch_job(job_id: int, fetcher: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(task_module, "HTTPPriceFetcher", FakeFetcher)
    monkeypatch.setattr(task_module, "run_http_fetch_job", fake_run_http_fetch_job)

    with pytest.raises(RuntimeError, match="boom"):
        task_module.http_fetch_job.run(123)
