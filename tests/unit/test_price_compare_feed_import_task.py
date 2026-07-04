from price_monitor.workers.celery_app import celery_app


def test_feed_import_task_is_registered() -> None:
    assert "price_monitor.feed_import.run" in celery_app.tasks
