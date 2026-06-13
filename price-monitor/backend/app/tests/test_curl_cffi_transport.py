import socket

import pytest

from app.transports.base import (
    TransportNetworkError,
    TransportResponse,
    TransportTimeoutError,
    TransportUnavailableError,
)
from app.transports.curl_cffi_transport import CurlCffiTransport


class _RequestsError(Exception):
    """Стенд-ин для curl_cffi.requests.exceptions.RequestsError."""


class _Timeout(_RequestsError):
    """Стенд-ин для curl_cffi.requests.exceptions.Timeout (подкласс RequestsError)."""


class _FakeExceptions:
    RequestsError = _RequestsError
    Timeout = _Timeout


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
        url: str = "https://shop.local/p/1",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html"}
        self.text = text
        self.url = url


class _FakeRequestsModule:
    """Лёгкий фейк curl_cffi.requests: записывает kwargs, отдаёт заданный response."""

    def __init__(
        self,
        *,
        response: _FakeResponse | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._response = response or _FakeResponse()
        self._raises = raises
        self.calls: list[dict] = []
        self.exceptions = _FakeExceptions()

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self._raises is not None:
            raise self._raises
        return self._response


def _fake_time_provider():
    """Детерминированный монотонный таймер: 1.0s -> 1.25s (250 ms)."""
    values = iter([1.0, 1.25])
    return lambda: next(values)


def test_adapter_calls_with_chrome_impersonate() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(impersonate="chrome", requests_module=fake)

    transport.fetch("https://shop.local/p/1")

    assert fake.calls[0]["impersonate"] == "chrome"


def test_adapter_calls_with_chrome_android_impersonate() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(impersonate="chrome_android", requests_module=fake)

    transport.fetch("https://shop.local/p/1")

    assert fake.calls[0]["impersonate"] == "chrome_android"


def test_adapter_calls_with_safari_impersonate() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(impersonate="safari", requests_module=fake)

    transport.fetch("https://shop.local/p/1")

    assert fake.calls[0]["impersonate"] == "safari"


def test_unknown_impersonate_profile_rejected() -> None:
    fake = _FakeRequestsModule()

    with pytest.raises(ValueError):
        CurlCffiTransport(impersonate="netscape", requests_module=fake)


def test_proxy_is_passed() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(requests_module=fake)

    transport.fetch(
        "https://shop.local/p/1", proxy_url="http://user:pass@127.0.0.1:8080"
    )

    assert fake.calls[0]["proxies"] == {
        "http": "http://user:pass@127.0.0.1:8080",
        "https": "http://user:pass@127.0.0.1:8080",
    }


def test_no_proxy_when_not_provided() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(requests_module=fake)

    transport.fetch("https://shop.local/p/1")

    assert "proxies" not in fake.calls[0]


def test_timeout_is_passed() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(requests_module=fake)

    transport.fetch("https://shop.local/p/1", timeout=7.5)

    assert fake.calls[0]["timeout"] == 7.5


def test_headers_are_passed() -> None:
    fake = _FakeRequestsModule()
    transport = CurlCffiTransport(requests_module=fake)

    transport.fetch("https://shop.local/p/1", headers={"Accept": "text/html"})

    assert fake.calls[0]["headers"] == {"Accept": "text/html"}


def test_403_returns_response_not_exception() -> None:
    fake = _FakeRequestsModule(
        response=_FakeResponse(status_code=403, text="Forbidden")
    )
    transport = CurlCffiTransport(requests_module=fake)

    result = transport.fetch("https://shop.local/p/1")

    assert isinstance(result, TransportResponse)
    assert result.status_code == 403


def test_timeout_exception_mapped() -> None:
    fake = _FakeRequestsModule(raises=_Timeout("timed out"))
    transport = CurlCffiTransport(requests_module=fake)

    with pytest.raises(TransportTimeoutError):
        transport.fetch("https://shop.local/p/1")


def test_network_exception_mapped() -> None:
    fake = _FakeRequestsModule(raises=_RequestsError("connection reset"))
    transport = CurlCffiTransport(requests_module=fake)

    with pytest.raises(TransportNetworkError):
        transport.fetch("https://shop.local/p/1")


def test_unavailable_when_curl_cffi_not_installed(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("curl_cffi"):
            raise ImportError("No module named 'curl_cffi'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    transport = CurlCffiTransport()

    with pytest.raises(TransportUnavailableError):
        transport.fetch("https://shop.local/p/1")


def test_response_fields_populated() -> None:
    fake = _FakeRequestsModule(
        response=_FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            text='{"price": 100}',
            url="https://shop.local/p/1?redirected=1",
        )
    )
    transport = CurlCffiTransport(
        requests_module=fake,
        time_provider=_fake_time_provider(),
    )

    result = transport.fetch("https://shop.local/p/1")

    assert result.status_code == 200
    assert result.text == '{"price": 100}'
    assert result.headers == {"Content-Type": "application/json; charset=utf-8"}
    assert result.content_type == "application/json; charset=utf-8"
    assert result.elapsed_ms == 250
    assert result.final_url == "https://shop.local/p/1?redirected=1"


def test_adapter_does_not_open_real_network(monkeypatch) -> None:
    network_calls = 0

    def fail_on_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("transport must not open real network connections")

    monkeypatch.setattr(socket, "create_connection", fail_on_network)

    fake = _FakeRequestsModule(response=_FakeResponse(status_code=200, text="ok"))
    transport = CurlCffiTransport(requests_module=fake)

    result = transport.fetch("https://shop.local/p/1")

    assert result.status_code == 200
    assert network_calls == 0
