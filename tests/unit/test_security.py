import pytest

from price_monitor.core.security import (
    AuthenticationError,
    build_signed_headers,
    verify_signed_request,
)


def test_hmac_signature_uses_method_path_body_hash_timestamp_and_request_id() -> None:
    body = b'{"url":"https://example.com/item"}'
    headers = build_signed_headers(
        secret="secret-a",
        method="POST",
        path="/api/v1/watchlist/items",
        body=body,
        request_id="req-1",
        timestamp=1_800_000_000,
    )

    verified = verify_signed_request(
        headers=headers,
        method="POST",
        path="/api/v1/watchlist/items",
        body=body,
        secrets=["secret-a"],
        now=1_800_000_030,
    )

    assert verified.request_id == "req-1"
    assert verified.body_sha256 == headers["X-Body-SHA256"]


def test_hmac_signature_rejects_body_tampering() -> None:
    headers = build_signed_headers(
        secret="secret-a",
        method="POST",
        path="/api/v1/watchlist/items",
        body=b'{"url":"https://example.com/item"}',
        request_id="req-1",
        timestamp=1_800_000_000,
    )

    with pytest.raises(AuthenticationError, match="body hash"):
        verify_signed_request(
            headers=headers,
            method="POST",
            path="/api/v1/watchlist/items",
            body=b'{"url":"https://example.com/changed"}',
            secrets=["secret-a"],
            now=1_800_000_030,
        )


def test_hmac_signature_rejects_stale_timestamp() -> None:
    headers = build_signed_headers(
        secret="secret-a",
        method="DELETE",
        path="/api/v1/watchlist/items/item-1",
        body=b"",
        request_id="req-2",
        timestamp=1_800_000_000,
    )

    with pytest.raises(AuthenticationError, match="timestamp"):
        verify_signed_request(
            headers=headers,
            method="DELETE",
            path="/api/v1/watchlist/items/item-1",
            body=b"",
            secrets=["secret-a"],
            now=1_800_001_000,
        )
