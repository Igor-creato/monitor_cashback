from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.clients.cashback_api import (
    CashbackAPIBadResponseError,
    CashbackAPINotFoundError,
    CashbackAPIUnavailableError,
)
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserLimitsNotFound,
    UserPriceMonitorLimits,
    get_price_monitor_limits,
)

SITE_ID = "savelloclub.ru"
EXTERNAL_USER_ID = "wp:savelloclub.ru:123"


class FakeCashbackClient:
    def __init__(
        self,
        response: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.external_user_ids: list[str] = []

    def get_user_price_monitor_limits(self, external_user_id: str) -> dict:
        self.external_user_ids.append(external_user_id)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("Unexpected limits API call.")
        return self.response


@pytest.fixture(autouse=True)
def forbid_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_real_http(*args, **kwargs):
        raise AssertionError("Tests must not perform real HTTP requests.")

    monkeypatch.setattr(httpx.Client, "request", fail_real_http)


@pytest.fixture(autouse=True)
def configured_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.user_limits.settings",
        SimpleNamespace(cashback_api_site_id=SITE_ID),
    )


def _api_response(user_share: object = 0.7) -> dict:
    return {
        "external_user_id": EXTERNAL_USER_ID,
        "tariff": "basic",
        "limits": {
            "max_tracked_products": 20,
            "history_days": 30,
            "min_fetch_interval_minutes": 360,
            "alerts_per_day": 10,
            "manual_refresh_per_day": 3,
            "browser_fallback_allowed": False,
        },
        "cashback": {
            "user_share": user_share,
            "cashback_currency": "RUB",
        },
    }


def _free_limits() -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id=EXTERNAL_USER_ID,
        tariff="free",
        limits=PriceMonitorLimitValues(
            max_tracked_products=0,
            history_days=30,
            min_fetch_interval_minutes=360,
            alerts_per_day=0,
            manual_refresh_per_day=0,
            browser_fallback_allowed=False,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0"),
            cashback_currency="RUB",
        ),
    )


def test_successful_response_is_parsed() -> None:
    client = FakeCashbackClient(response=_api_response())

    result = get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID, client=client)

    assert result == UserPriceMonitorLimits(
        external_user_id=EXTERNAL_USER_ID,
        tariff="basic",
        limits=PriceMonitorLimitValues(
            max_tracked_products=20,
            history_days=30,
            min_fetch_interval_minutes=360,
            alerts_per_day=10,
            manual_refresh_per_day=3,
            browser_fallback_allowed=False,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0.7"),
            cashback_currency="RUB",
        ),
    )
    assert client.external_user_ids == [EXTERNAL_USER_ID]


def test_404_returns_user_limits_not_found() -> None:
    client = FakeCashbackClient(
        error=CashbackAPINotFoundError("Cashback API resource was not found.")
    )

    result = get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID, client=client)

    assert isinstance(result, UserLimitsNotFound)
    assert client.external_user_ids == [EXTERNAL_USER_ID]


def test_500_returns_free_limits() -> None:
    client = FakeCashbackClient(
        error=CashbackAPIUnavailableError("Cashback API is unavailable.")
    )

    result = get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID, client=client)

    assert result == _free_limits()
    assert client.external_user_ids == [EXTERNAL_USER_ID]


def test_malformed_response_returns_free_limits() -> None:
    client = FakeCashbackClient(
        response={
            "external_user_id": EXTERNAL_USER_ID,
            "tariff": "basic",
            "limits": {"max_tracked_products": 20},
            "cashback": {"user_share": "not-a-decimal", "cashback_currency": "RUB"},
        }
    )

    result = get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID, client=client)

    assert result == _free_limits()
    assert client.external_user_ids == [EXTERNAL_USER_ID]


def test_bad_response_error_returns_free_limits() -> None:
    client = FakeCashbackClient(
        error=CashbackAPIBadResponseError("Cashback API returned invalid JSON.")
    )

    result = get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID, client=client)

    assert result == _free_limits()
    assert client.external_user_ids == [EXTERNAL_USER_ID]


def test_user_share_is_returned_as_decimal() -> None:
    client = FakeCashbackClient(response=_api_response(user_share="0.7"))

    result = get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID, client=client)

    assert isinstance(result, UserPriceMonitorLimits)
    assert result.cashback.user_share == Decimal("0.7")


def test_site_mismatch_returns_free_limits_without_api_call() -> None:
    client = FakeCashbackClient(response=_api_response())

    result = get_price_monitor_limits(
        "other-site.test",
        EXTERNAL_USER_ID,
        client=client,
    )

    assert result == _free_limits()
    assert client.external_user_ids == []


def test_tests_forbid_real_http_requests() -> None:
    with pytest.raises(AssertionError, match="real HTTP"):
        get_price_monitor_limits(SITE_ID, EXTERNAL_USER_ID)
