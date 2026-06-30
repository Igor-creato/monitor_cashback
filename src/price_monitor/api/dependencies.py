from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from price_monitor.core.config import Settings
from price_monitor.core.security import VerifiedRequest, verify_signed_request
from price_monitor.db.session import get_session


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return Settings()


get_db_session = get_session


async def verify_wordpress_request(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> VerifiedRequest:
    body = await request.body()
    signed_query = request.url.query if request.method.upper() == "GET" else None
    return verify_signed_request(
        headers=request.headers,
        method=request.method,
        path=request.url.path,
        query=signed_query,
        body=body,
        secrets=settings.hmac_secret_list,
        replay_window_seconds=settings.hmac_replay_window_seconds,
    )
