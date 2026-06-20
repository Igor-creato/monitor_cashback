from __future__ import annotations

from typing import Any

SECRET_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "tokens",
    "cookie",
    "cookies",
    "authorization",
    "api_key",
    "apikey",
    "headers",
    "access_key",
    "private_key",
)


def is_secret_like_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def strip_secret_like_keys(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if is_secret_like_key(key_text):
                continue
            safe[key_text] = strip_secret_like_keys(child)
        return safe
    if isinstance(value, list):
        return [strip_secret_like_keys(child) for child in value]
    return value
