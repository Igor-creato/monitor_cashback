import pytest
from fastapi.testclient import TestClient

from price_monitor.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())
