from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: dict[str, str]
    text: str
    content_type: str
    elapsed_ms: int
    final_url: str


class TransportError(Exception):
    """Базовая ошибка транспорт-слоя."""


class TransportTimeoutError(TransportError):
    """Запрос превысил таймаут."""


class TransportNetworkError(TransportError):
    """Прочий сетевой сбой (DNS, connect, reset и т.п.)."""


class TransportUnavailableError(TransportError):
    """Транспорт недоступен: отсутствует системная/опциональная зависимость."""
