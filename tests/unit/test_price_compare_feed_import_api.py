from fastapi.testclient import TestClient

from price_monitor.main import create_app


class FakeAsyncResult:
    id = "feed-import-task-123"


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
        "poll_url": "/api/v1/stores",
    }
    assert "secret" not in response.text.lower()
