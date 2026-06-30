from __future__ import annotations

import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode


class AuthenticationError(Exception):
    """Raised when a WordPress proxy request cannot be authenticated."""


@dataclass(frozen=True)
class VerifiedRequest:
    request_id: str
    timestamp: int
    body_sha256: str


def hash_body(body: bytes) -> str:
    return sha256(body).hexdigest()


def _canonical_message(
    *, method: str, path: str, timestamp: int, request_id: str, body_sha256: str
) -> bytes:
    normalized = "\n".join(
        [
            method.upper(),
            path,
            str(timestamp),
            request_id,
            body_sha256,
        ]
    )
    return normalized.encode("utf-8")


def _canonical_request_target(path: str, query: str | None = None) -> str:
    if query is None:
        return path

    normalized_query = urlencode(sorted(parse_qsl(query, keep_blank_values=True)))
    if not normalized_query:
        return path
    return f"{path}?{normalized_query}"


def _signature(
    *,
    secret: str,
    method: str,
    path: str,
    query: str | None,
    timestamp: int,
    request_id: str,
    body_sha256: str,
) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        _canonical_message(
            method=method,
            path=_canonical_request_target(path, query),
            timestamp=timestamp,
            request_id=request_id,
            body_sha256=body_sha256,
        ),
        sha256,
    ).hexdigest()


def build_signed_headers(
    *,
    secret: str,
    method: str,
    path: str,
    query: str | None = None,
    body: bytes,
    request_id: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    issued_at = int(time.time()) if timestamp is None else timestamp
    body_sha256 = hash_body(body)
    signature = _signature(
        secret=secret,
        method=method,
        path=path,
        query=query,
        timestamp=issued_at,
        request_id=request_id,
        body_sha256=body_sha256,
    )
    return {
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
        "X-Request-Timestamp": str(issued_at),
        "X-Body-SHA256": body_sha256,
        "X-Signature": signature,
    }


def verify_signed_request(
    *,
    headers: Mapping[str, str],
    method: str,
    path: str,
    query: str | None = None,
    body: bytes,
    secrets: list[str],
    now: int | None = None,
    replay_window_seconds: int = 300,
) -> VerifiedRequest:
    if not secrets:
        raise AuthenticationError("no HMAC secrets configured")

    request_id = headers.get("X-Request-Id")
    raw_timestamp = headers.get("X-Request-Timestamp")
    expected_body_hash = headers.get("X-Body-SHA256")
    provided_signature = headers.get("X-Signature")
    if not request_id or not raw_timestamp or not expected_body_hash or not provided_signature:
        raise AuthenticationError("missing authentication headers")

    try:
        timestamp = int(raw_timestamp)
    except ValueError as exc:
        raise AuthenticationError("timestamp must be an integer") from exc

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp) > replay_window_seconds:
        raise AuthenticationError("timestamp outside replay window")

    actual_body_hash = hash_body(body)
    if not hmac.compare_digest(actual_body_hash, expected_body_hash):
        raise AuthenticationError("body hash mismatch")

    for secret in secrets:
        expected_signature = _signature(
            secret=secret,
            method=method,
            path=path,
            query=query,
            timestamp=timestamp,
            request_id=request_id,
            body_sha256=actual_body_hash,
        )
        if hmac.compare_digest(expected_signature, provided_signature):
            return VerifiedRequest(
                request_id=request_id,
                timestamp=timestamp,
                body_sha256=actual_body_hash,
            )

    raise AuthenticationError("signature mismatch")
