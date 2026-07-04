from price_monitor.workers.celery_app import celery_app


def test_feed_import_task_is_registered() -> None:
    assert "price_monitor.feed_import.run" in celery_app.tasks


def test_feed_import_task_is_scheduled_for_feed_freshness() -> None:
    schedule = celery_app.conf.beat_schedule["price-monitor-feed-import-refresh"]

    assert schedule["task"] == "price_monitor.feed_import.run"
    assert schedule["schedule"] == 21_600
    assert schedule["options"]["queue"] == "monitor-cashback.default"
    assert schedule["options"]["routing_key"] == "default"
