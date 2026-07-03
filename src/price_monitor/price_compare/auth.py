from __future__ import annotations

from fastapi import Request

from price_monitor.core.config import Settings
from price_monitor.core.security import VerifiedRequest, verify_signed_request


async def require_signed_request(request: Request) -> VerifiedRequest | None:
    settings: Settings = request.app.state.settings
    secrets = settings.hmac_secret_list
    if not secrets:
        return None

    body = await request.body()
    return verify_signed_request(
        headers=request.headers,
        method=request.method,
        path=request.url.path,
        query=request.url.query or None,
        body=body,
        secrets=secrets,
        replay_window_seconds=settings.hmac_replay_window_seconds,
    )
