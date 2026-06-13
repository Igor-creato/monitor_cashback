from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
DEFAULT_MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


@dataclass(frozen=True)
class StoredImage:
    """Результат попытки скопировать картинку товара в S3-хранилище.

    `copied=True` только если картинка реально загружена в bucket. В любом
    fail-soft сценарии (storage disabled, download/validation/storage error)
    возвращается исходный `image_url`, `copied=False` и `reason`.
    """

    image_url: str
    object_key: str | None
    copied: bool
    content_type: str | None
    reason: str | None


class ImageValidationError(Exception):
    """Картинка не прошла валидацию (content-type, размер, пустой контент)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ImageDownloadError(Exception):
    """Не удалось скачать картинку по URL."""


class ObjectStorageUnavailableError(Exception):
    """S3-клиент недоступен: отсутствует опциональная зависимость boto3."""


class ImageTransport(Protocol):
    """Минимальный байтовый транспорт для загрузки картинки."""

    def fetch(self, url: str) -> Any:  # pragma: no cover - протокол
        ...


def normalize_image_url(url: str) -> str:
    """Нормализует URL картинки.

    - обрезает пробелы, отклоняет пустую строку;
    - protocol-relative `//host/path` приводит к `https:`;
    - разрешает только схемы http/https.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise ImageValidationError("empty_url")

    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ImageValidationError("unsupported_scheme")

    return candidate


def download_image(url: str, transport: ImageTransport) -> tuple[bytes, str]:
    """Скачивает картинку через переданный транспорт.

    Возвращает `(content_bytes, content_type)`. Любой сбой транспорта
    оборачивается в `ImageDownloadError`, чтобы вызывающая сторона могла
    отработать fail-soft и не уронить price fetch.
    """
    try:
        response = transport.fetch(url)
        content = bytes(response.content)
        content_type = str(getattr(response, "content_type", "") or "")
    except Exception as exc:  # noqa: BLE001 - оборачиваем любой сбой транспорта
        raise ImageDownloadError("download_failed") from exc

    return content, content_type


def validate_image(
    content: bytes,
    content_type: str,
    max_size: int = DEFAULT_MAX_IMAGE_SIZE,
) -> str:
    """Валидирует контент картинки. Возвращает нормализованный content-type."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()

    if normalized not in ALLOWED_CONTENT_TYPES:
        raise ImageValidationError("unsupported_content_type")
    if not content:
        raise ImageValidationError("empty_content")
    if len(content) > max_size:
        raise ImageValidationError("too_large")

    return normalized


def build_public_image_url(object_key: str) -> str:
    """Строит публичный URL картинки из object_key и базового URL хранилища."""
    base_url = settings.object_storage_public_base_url.strip().rstrip("/")
    key = object_key.strip().lstrip("/")
    return f"{base_url}/{quote(key, safe='/')}"


def store_product_image(
    tracked_product_id: int,
    image_url: str,
    *,
    transport: ImageTransport | None = None,
    s3_client: Any | None = None,
    settings: Settings = settings,
    max_size: int = DEFAULT_MAX_IMAGE_SIZE,
) -> StoredImage:
    """Копирует картинку товара в S3-хранилище (fail-soft).

    Если хранилище выключено — возвращает исходный URL без обращения к
    транспорту/S3. При любом сбое скачивания, валидации или хранилища не
    пробрасывает исключение, а возвращает `copied=False` с причиной, чтобы
    не ломать price fetch вызывающей стороны.
    """
    if not settings.object_storage_enabled:
        return StoredImage(
            image_url=image_url,
            object_key=None,
            copied=False,
            content_type=None,
            reason="storage_disabled",
        )

    try:
        normalized_url = normalize_image_url(image_url)
        active_transport = transport or _default_transport()
        content, raw_content_type = download_image(normalized_url, active_transport)
        content_type = validate_image(content, raw_content_type, max_size)

        digest = hashlib.sha256(content).hexdigest()
        ext = _CONTENT_TYPE_EXTENSIONS[content_type]
        object_key = f"products/{tracked_product_id}/{digest}.{ext}"

        client = s3_client or _default_s3_client(settings)
        client.put_object(
            settings.object_storage_bucket,
            object_key,
            content,
            content_type,
        )
    except ImageValidationError as exc:
        logger.warning(
            "product image not copied: validation failed (product_id=%s, reason=%s)",
            tracked_product_id,
            exc.reason,
        )
        return _not_copied(image_url, exc.reason)
    except ImageDownloadError:
        logger.warning(
            "product image not copied: download failed (product_id=%s)",
            tracked_product_id,
        )
        return _not_copied(image_url, "download_failed")
    except ObjectStorageUnavailableError:
        logger.warning(
            "product image not copied: object storage unavailable (product_id=%s)",
            tracked_product_id,
        )
        return _not_copied(image_url, "storage_unavailable")
    except Exception:  # noqa: BLE001 - сбой хранилища не должен ломать caller
        logger.warning(
            "product image not copied: storage error (product_id=%s)",
            tracked_product_id,
        )
        return _not_copied(image_url, "storage_error")

    return StoredImage(
        image_url=build_public_image_url(object_key),
        object_key=object_key,
        copied=True,
        content_type=content_type,
        reason=None,
    )


def _not_copied(image_url: str, reason: str) -> StoredImage:
    return StoredImage(
        image_url=image_url,
        object_key=None,
        copied=False,
        content_type=None,
        reason=reason,
    )


def _default_transport() -> ImageTransport:
    # Реальный байтовый транспорт подключается на шаге интеграции с fetch
    # pipeline. На текущем шаге сервис всегда вызывается с инъекцией транспорта,
    # поэтому дефолтный транспорт ещё не реализован.
    raise ObjectStorageUnavailableError(
        "no default image transport configured; pass an explicit transport"
    )


def _default_s3_client(settings: Settings) -> _ObjectStorageClient:
    return _ObjectStorageClient(settings=settings)


class _ObjectStorageClient:
    """Адаптер поверх boto3 для S3-совместимого хранилища (MinIO/S3).

    boto3 импортируется лениво при первом вызове, чтобы импорт модуля и тесты
    не требовали установленного пакета. Секреты не логируются и берутся из
    SecretStr только в момент создания клиента.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    def put_object(
        self,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        client = self._get_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise ObjectStorageUnavailableError(
                "boto3 is not installed; install the optional 'boto3' package "
                "to use object storage"
            ) from exc

        self._client = boto3.client(
            "s3",
            endpoint_url=self._settings.object_storage_endpoint or None,
            aws_access_key_id=(
                self._settings.object_storage_access_key.get_secret_value() or None
            ),
            aws_secret_access_key=(
                self._settings.object_storage_secret_key.get_secret_value() or None
            ),
        )
        return self._client
