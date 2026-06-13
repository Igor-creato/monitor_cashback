from __future__ import annotations

import hashlib

import pytest

from app.core import config
from app.services.image_storage import (
    DEFAULT_MAX_IMAGE_SIZE,
    ImageValidationError,
    StoredImage,
    build_public_image_url,
    download_image,
    normalize_image_url,
    store_product_image,
    validate_image,
)


class _FakeImageResponse:
    """Стенд-ин ответа байтового транспорта: отдаёт content + content_type."""

    def __init__(self, *, content: bytes, content_type: str) -> None:
        self.content = content
        self.content_type = content_type


class _FakeTransport:
    """Лёгкий фейк транспорта: записывает вызовы, отдаёт заданный response."""

    def __init__(
        self,
        *,
        response: _FakeImageResponse | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[str] = []

    def fetch(self, url: str) -> _FakeImageResponse:
        self.calls.append(url)
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return self._response


class _FakeS3Client:
    """Фейк S3-клиента: фиксирует put_object вызовы, ничего не отправляет."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(
        self, bucket: str, key: str, content: bytes, content_type: str
    ) -> None:
        self.calls.append(
            {
                "bucket": bucket,
                "key": key,
                "content": content,
                "content_type": content_type,
            }
        )


class _RaisingS3Client:
    """Фейк S3-клиента, который падает на put_object и считает вызовы."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises or RuntimeError("s3 boom")
        self.calls: list[dict] = []

    def put_object(
        self, bucket: str, key: str, content: bytes, content_type: str
    ) -> None:
        self.calls.append({"bucket": bucket, "key": key})
        raise self._raises


@pytest.fixture
def _enabled_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "object_storage_enabled", True)
    monkeypatch.setattr(config.settings, "object_storage_bucket", "product-images")
    monkeypatch.setattr(
        config.settings,
        "object_storage_public_base_url",
        "https://cdn.example.com/img",
    )


def _object_key(tracked_product_id: int, content: bytes, ext: str) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"products/{tracked_product_id}/{digest}.{ext}"


def test_valid_jpeg_is_stored(_enabled_storage: None) -> None:
    content = b"\xff\xd8\xff\xe0jpeg-bytes"
    transport = _FakeTransport(
        response=_FakeImageResponse(content=content, content_type="image/jpeg")
    )
    s3 = _FakeS3Client()

    result = store_product_image(
        42,
        "https://shop.local/img/1.jpg",
        transport=transport,
        s3_client=s3,
    )

    assert isinstance(result, StoredImage)
    assert result.copied is True
    assert result.content_type == "image/jpeg"
    assert result.object_key == _object_key(42, content, "jpg")
    assert result.image_url == ("https://cdn.example.com/img/" + result.object_key)
    assert len(s3.calls) == 1
    assert s3.calls[0]["bucket"] == "product-images"
    assert s3.calls[0]["key"] == result.object_key
    assert s3.calls[0]["content"] == content
    assert s3.calls[0]["content_type"] == "image/jpeg"


def test_valid_webp_is_stored(_enabled_storage: None) -> None:
    content = b"RIFF....WEBPvp8"
    transport = _FakeTransport(
        response=_FakeImageResponse(content=content, content_type="image/webp")
    )
    s3 = _FakeS3Client()

    result = store_product_image(
        7,
        "https://shop.local/img/x.webp",
        transport=transport,
        s3_client=s3,
    )

    assert result.copied is True
    assert result.object_key == _object_key(7, content, "webp")
    assert len(s3.calls) == 1


def test_valid_png_is_stored(_enabled_storage: None) -> None:
    content = b"\x89PNG\r\n\x1a\npng-bytes"
    transport = _FakeTransport(
        response=_FakeImageResponse(content=content, content_type="image/png")
    )
    s3 = _FakeS3Client()

    result = store_product_image(
        9,
        "https://shop.local/img/y.png",
        transport=transport,
        s3_client=s3,
    )

    assert result.copied is True
    assert result.object_key == _object_key(9, content, "png")
    assert len(s3.calls) == 1


def test_html_content_is_rejected(_enabled_storage: None) -> None:
    transport = _FakeTransport(
        response=_FakeImageResponse(
            content=b"<html>not an image</html>", content_type="text/html"
        )
    )
    s3 = _FakeS3Client()

    result = store_product_image(
        1,
        "https://shop.local/img/notimg",
        transport=transport,
        s3_client=s3,
    )

    assert result.copied is False
    assert result.object_key is None
    assert result.reason == "unsupported_content_type"
    assert result.image_url == "https://shop.local/img/notimg"
    assert s3.calls == []


def test_oversized_image_is_rejected(_enabled_storage: None) -> None:
    big = b"x" * (DEFAULT_MAX_IMAGE_SIZE + 1)
    transport = _FakeTransport(
        response=_FakeImageResponse(content=big, content_type="image/jpeg")
    )
    s3 = _FakeS3Client()

    result = store_product_image(
        1,
        "https://shop.local/img/big.jpg",
        transport=transport,
        s3_client=s3,
    )

    assert result.copied is False
    assert result.reason == "too_large"
    assert s3.calls == []


def test_storage_error_does_not_break_caller(_enabled_storage: None) -> None:
    content = b"\xff\xd8\xff\xe0jpeg-bytes"
    transport = _FakeTransport(
        response=_FakeImageResponse(content=content, content_type="image/jpeg")
    )
    s3 = _RaisingS3Client()

    result = store_product_image(
        5,
        "https://shop.local/img/1.jpg",
        transport=transport,
        s3_client=s3,
    )

    # Сбой хранилища не пробрасывается наружу — caller (price fetch) не падает.
    assert result.copied is False
    assert result.object_key is None
    assert result.reason is not None
    assert result.image_url == "https://shop.local/img/1.jpg"
    assert len(s3.calls) == 1


def test_download_error_does_not_break_caller(_enabled_storage: None) -> None:
    transport = _FakeTransport(raises=RuntimeError("network down"))
    s3 = _FakeS3Client()

    result = store_product_image(
        5,
        "https://shop.local/img/1.jpg",
        transport=transport,
        s3_client=s3,
    )

    assert result.copied is False
    assert result.reason == "download_failed"
    assert result.image_url == "https://shop.local/img/1.jpg"
    assert s3.calls == []


def test_storage_disabled_returns_original_and_skips_s3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "object_storage_enabled", False)
    transport = _FakeTransport(raises=AssertionError("transport must not be used"))
    s3 = _RaisingS3Client(raises=AssertionError("s3 must not be used"))

    result = store_product_image(
        1,
        "https://shop.local/img/keep.jpg",
        transport=transport,
        s3_client=s3,
    )

    assert result.copied is False
    assert result.reason == "storage_disabled"
    assert result.object_key is None
    assert result.image_url == "https://shop.local/img/keep.jpg"
    # Ни транспорт, ни S3-клиент не должны быть вызваны.
    assert transport.calls == []
    assert s3.calls == []


def test_build_public_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config.settings,
        "object_storage_public_base_url",
        "https://cdn.example.com/img/",
    )

    url = build_public_image_url("products/1/ab.jpg")

    assert url == "https://cdn.example.com/img/products/1/ab.jpg"


def test_validate_image_accepts_content_type_with_charset() -> None:
    normalized = validate_image(b"jpeg-bytes", "image/jpeg; charset=binary")

    assert normalized == "image/jpeg"


def test_validate_image_rejects_unsupported_type() -> None:
    with pytest.raises(ImageValidationError):
        validate_image(b"data", "text/html")


def test_normalize_image_url_upgrades_protocol_relative() -> None:
    assert normalize_image_url("//cdn.shop.local/a.jpg") == (
        "https://cdn.shop.local/a.jpg"
    )


def test_normalize_image_url_rejects_empty() -> None:
    with pytest.raises(ImageValidationError):
        normalize_image_url("   ")


def test_download_image_returns_bytes_and_content_type() -> None:
    transport = _FakeTransport(
        response=_FakeImageResponse(content=b"abc", content_type="image/png")
    )

    content, content_type = download_image("https://shop.local/a.png", transport)

    assert content == b"abc"
    assert content_type == "image/png"
    assert transport.calls == ["https://shop.local/a.png"]


def test_object_key_is_deterministic_for_same_content(
    _enabled_storage: None,
) -> None:
    content = b"\xff\xd8\xff\xe0same"
    s3_a = _FakeS3Client()
    s3_b = _FakeS3Client()

    result_a = store_product_image(
        3,
        "https://shop.local/img/a.jpg",
        transport=_FakeTransport(
            response=_FakeImageResponse(content=content, content_type="image/jpeg")
        ),
        s3_client=s3_a,
    )
    result_b = store_product_image(
        3,
        "https://shop.local/img/a.jpg",
        transport=_FakeTransport(
            response=_FakeImageResponse(content=content, content_type="image/jpeg")
        ),
        s3_client=s3_b,
    )

    assert result_a.object_key == result_b.object_key
