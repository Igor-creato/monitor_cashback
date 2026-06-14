from __future__ import annotations

import builtins
import socket
from typing import Any

import pytest

from app.fetchers.browser_fetcher import BrowserFetchResult
from app.fetchers.camoufox_fetcher import (
    CamoufoxUnavailableError,
    fetch_with_camoufox,
)


class _FakeResponse:
    status = 200


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://shop.local/p/1?rendered=1"
        self.evaluate_calls: list[tuple[str, str]] = []
        self.goto_calls: list[dict[str, Any]] = []

    def evaluate(self, script: str, arg: str) -> None:
        self.evaluate_calls.append((script, arg))

    def goto(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.goto_calls.append({"url": url, **kwargs})
        return _FakeResponse()

    def content(self) -> str:
        return "<html><body>Rendered by Camoufox</body></html>"


class _FakeBrowser:
    def __init__(self) -> None:
        self.page = _FakePage()

    def new_page(self) -> _FakePage:
        return self.page


class _FakeCamoufoxFactory:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.browser = _FakeBrowser()
        self._raises = raises

    def __call__(self, **kwargs: Any) -> _FakeCamoufoxFactory:
        self.calls.append(kwargs)
        return self

    def __enter__(self) -> _FakeBrowser:
        if self._raises is not None:
            raise self._raises
        return self.browser

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_fake_camoufox_returns_browser_fetch_result(monkeypatch) -> None:
    fake_camoufox = _FakeCamoufoxFactory()
    monkeypatch.setattr(
        "app.fetchers.camoufox_fetcher._load_camoufox",
        lambda: fake_camoufox,
    )

    result = fetch_with_camoufox("https://shop.local/p/1")

    assert isinstance(result, BrowserFetchResult)
    assert result.final_url == "https://shop.local/p/1?rendered=1"
    assert result.html == "<html><body>Rendered by Camoufox</body></html>"
    assert result.response_status == 200
    assert result.screenshot_object_key is None
    assert result.browser_engine == "camoufox"
    assert result.debug_info == {
        "adapter": "camoufox",
        "proxy_enabled": False,
        "locale": "ru-RU",
        "timezone": "Europe/Moscow",
    }


def test_proxy_options_are_passed_to_camoufox(monkeypatch) -> None:
    fake_camoufox = _FakeCamoufoxFactory()
    monkeypatch.setattr(
        "app.fetchers.camoufox_fetcher._load_camoufox",
        lambda: fake_camoufox,
    )

    fetch_with_camoufox(
        "https://shop.local/p/1",
        proxy_url="http://user:pass@127.0.0.1:8080",
    )

    assert fake_camoufox.calls[0]["proxy"] == {
        "server": "http://user:pass@127.0.0.1:8080"
    }


def test_locale_and_timezone_are_applied(monkeypatch) -> None:
    fake_camoufox = _FakeCamoufoxFactory()
    monkeypatch.setattr(
        "app.fetchers.camoufox_fetcher._load_camoufox",
        lambda: fake_camoufox,
    )

    fetch_with_camoufox(
        "https://shop.local/p/1",
        locale="en-US",
        timezone="America/New_York",
    )

    assert fake_camoufox.calls[0]["locale"] == "en-US"
    assert fake_camoufox.browser.page.evaluate_calls == [
        ("(tz) => window.setTimezone(tz)", "America/New_York")
    ]


def test_timeout_is_passed_to_goto_in_milliseconds(monkeypatch) -> None:
    fake_camoufox = _FakeCamoufoxFactory()
    monkeypatch.setattr(
        "app.fetchers.camoufox_fetcher._load_camoufox",
        lambda: fake_camoufox,
    )

    fetch_with_camoufox("https://shop.local/p/1", timeout=7.5)

    assert fake_camoufox.browser.page.goto_calls == [
        {"url": "https://shop.local/p/1", "timeout": 7500}
    ]


def test_missing_camoufox_module_raises_typed_error(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("camoufox"):
            raise ImportError("No module named 'camoufox'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(CamoufoxUnavailableError, match="camoufox is not installed"):
        fetch_with_camoufox("https://shop.local/p/1")


def test_launch_failure_maps_to_typed_error(monkeypatch) -> None:
    fake_camoufox = _FakeCamoufoxFactory(raises=RuntimeError("launch failed"))
    monkeypatch.setattr(
        "app.fetchers.camoufox_fetcher._load_camoufox",
        lambda: fake_camoufox,
    )

    with pytest.raises(CamoufoxUnavailableError, match="camoufox launch failed"):
        fetch_with_camoufox("https://shop.local/p/1")


def test_unit_fetcher_does_not_open_real_browser_or_network(monkeypatch) -> None:
    network_calls = 0

    def fail_on_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("camoufox unit tests must not open network")

    fake_camoufox = _FakeCamoufoxFactory()
    monkeypatch.setattr(socket, "create_connection", fail_on_network)
    monkeypatch.setattr(
        "app.fetchers.camoufox_fetcher._load_camoufox",
        lambda: fake_camoufox,
    )

    result = fetch_with_camoufox("https://shop.local/p/1")

    assert result.response_status == 200
    assert network_calls == 0
