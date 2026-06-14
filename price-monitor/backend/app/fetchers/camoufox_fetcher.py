from __future__ import annotations

import time
from typing import Any

from app.fetchers.browser_fetcher import BrowserFetchResult


class CamoufoxUnavailableError(Exception):
    """Camoufox is unavailable because dependency import or browser launch failed."""


def fetch_with_camoufox(
    url: str,
    proxy_url: str | None = None,
    locale: str = "ru-RU",
    timezone: str = "Europe/Moscow",
    timeout: float | None = None,
) -> BrowserFetchResult:
    camoufox = _load_camoufox()
    launch_options: dict[str, Any] = {
        "headless": True,
        "locale": locale,
    }
    if proxy_url is not None:
        launch_options["proxy"] = {"server": proxy_url}

    started = time.monotonic()
    try:
        with camoufox(**launch_options) as browser:
            page = browser.new_page()
            page.evaluate("(tz) => window.setTimezone(tz)", timezone)
            goto_options: dict[str, Any] = {}
            if timeout is not None:
                goto_options["timeout"] = int(timeout * 1000)
            response = page.goto(url, **goto_options)
            html = page.content()
            final_url = page.url
    except CamoufoxUnavailableError:
        raise
    except Exception as exc:
        raise CamoufoxUnavailableError("camoufox launch failed") from exc

    return BrowserFetchResult(
        final_url=final_url,
        html=html,
        screenshot_object_key=None,
        response_status=response.status if response is not None else None,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        browser_engine="camoufox",
        debug_info={
            "adapter": "camoufox",
            "proxy_enabled": proxy_url is not None,
            "locale": locale,
            "timezone": timezone,
        },
    )


def _load_camoufox() -> Any:
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as exc:
        raise CamoufoxUnavailableError(
            "camoufox is not installed; install the optional 'camoufox' package "
            "to use fetch_with_camoufox"
        ) from exc
    return Camoufox
