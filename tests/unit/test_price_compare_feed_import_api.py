from fastapi.testclient import TestClient

from price_monitor.main import create_app


class FakeAsyncResult:
    id = "feed-import-task-123"


class FakeTaskStatus:
    state = "SUCCESS"
    info = {
        "status": "success",
        "created_count": 2,
        "updated_count": 1,
        "skipped_count": 0,
        "quarantined_count": 0,
        "feed_url": "https://feeds.example/catalog.yml?pass=unit-secret",
    }


def test_feed_import_api_enqueues_import_task_without_secret_payload(monkeypatch) -> None:
    calls: list[object] = []

    def fake_delay() -> FakeAsyncResult:
        calls.append(object())
        return FakeAsyncResult()

    monkeypatch.setattr(
        "price_monitor.workers.tasks.feed_import.run_feed_import.delay",
        fake_delay,
    )
    client = TestClient(create_app())

    response = client.post("/api/v1/feed-import/runs")

    assert response.status_code == 202
    assert calls
    assert response.json() == {
        "status": "accepted",
        "task_id": "feed-import-task-123",
        "poll_url": "/api/v1/feed-import/tasks/feed-import-task-123",
    }
    assert "secret" not in response.text.lower()


def test_feed_import_api_returns_safe_task_status_without_secret_payload(monkeypatch) -> None:
    seen_task_ids: list[str] = []

    def fake_async_result(task_id: str) -> FakeTaskStatus:
        seen_task_ids.append(task_id)
        return FakeTaskStatus()

    monkeypatch.setattr(
        "price_monitor.api.v1.feed_import.run_feed_import.AsyncResult",
        fake_async_result,
    )
    client = TestClient(create_app())

    response = client.get("/api/v1/feed-import/tasks/feed-import-task-123")

    assert response.status_code == 200
    assert seen_task_ids == ["feed-import-task-123"]
    assert response.json() == {
        "status": "ok",
        "task_id": "feed-import-task-123",
        "state": "success",
        "result": {
            "status": "success",
            "created_count": 2,
            "updated_count": 1,
            "skipped_count": 0,
            "quarantined_count": 0,
        },
    }
    assert "unit-secret" not in response.text
    assert "pass=" not in response.text


def test_feed_import_task_status_rejects_invalid_task_id() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/feed-import/tasks/bad%20task")

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_FEED_IMPORT_TASK"
