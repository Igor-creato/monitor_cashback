from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.clients.cashback_api import (
    CashbackAPIClient,
    CashbackAPIError,
    CashbackAPINotFoundError,
)
from app.core.config import settings


@dataclass(frozen=True)
class PriceMonitorLimitValues:
    max_tracked_products: int
    history_days: int
    min_fetch_interval_minutes: int
    alerts_per_day: int
    manual_refresh_per_day: int
    browser_fallback_allowed: bool


@dataclass(frozen=True)
class CashbackLimitValues:
    user_share: Decimal
    cashback_currency: str


@dataclass(frozen=True)
class UserPriceMonitorLimits:
    external_user_id: str
    tariff: str
    limits: PriceMonitorLimitValues
    cashback: CashbackLimitValues


@dataclass(frozen=True)
class UserLimitsNotFound:
    pass


def get_price_monitor_limits(
    site_id,
    external_user_id,
    *,
    client: CashbackAPIClient | None = None,
) -> UserPriceMonitorLimits | UserLimitsNotFound:
    requested_external_user_id = str(external_user_id)
    if str(site_id) != settings.cashback_api_site_id:
        return _free_limits(requested_external_user_id)

    api_client = client or CashbackAPIClient()
    try:
        response = api_client.get_user_price_monitor_limits(requested_external_user_id)
    except CashbackAPINotFoundError:
        return UserLimitsNotFound()
    except CashbackAPIError:
        return _free_limits(requested_external_user_id)

    parsed = _parse_response(response, requested_external_user_id)
    if parsed is None:
        return _free_limits(requested_external_user_id)
    return parsed


def _free_limits(external_user_id: str) -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id=external_user_id,
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


def _parse_response(
    response: Any,
    requested_external_user_id: str,
) -> UserPriceMonitorLimits | None:
    if not isinstance(response, dict):
        return None

    response_external_user_id = response.get("external_user_id")
    tariff = response.get("tariff")
    limits = response.get("limits")
    cashback = response.get("cashback")

    if response_external_user_id != requested_external_user_id:
        return None
    if not isinstance(tariff, str) or tariff == "":
        return None
    if not isinstance(limits, dict) or not isinstance(cashback, dict):
        return None

    parsed_limits = _parse_limits(limits)
    parsed_cashback = _parse_cashback(cashback)
    if parsed_limits is None or parsed_cashback is None:
        return None

    return UserPriceMonitorLimits(
        external_user_id=requested_external_user_id,
        tariff=tariff,
        limits=parsed_limits,
        cashback=parsed_cashback,
    )


def _parse_limits(limits: dict[str, Any]) -> PriceMonitorLimitValues | None:
    max_tracked_products = _int_value(limits.get("max_tracked_products"))
    history_days = _int_value(limits.get("history_days"))
    min_fetch_interval_minutes = _int_value(
        limits.get("min_fetch_interval_minutes")
    )
    alerts_per_day = _int_value(limits.get("alerts_per_day"))
    manual_refresh_per_day = _int_value(limits.get("manual_refresh_per_day"))
    browser_fallback_allowed = limits.get("browser_fallback_allowed")

    if (
        max_tracked_products is None
        or history_days is None
        or min_fetch_interval_minutes is None
        or alerts_per_day is None
        or manual_refresh_per_day is None
        or not isinstance(browser_fallback_allowed, bool)
    ):
        return None

    return PriceMonitorLimitValues(
        max_tracked_products=max_tracked_products,
        history_days=history_days,
        min_fetch_interval_minutes=min_fetch_interval_minutes,
        alerts_per_day=alerts_per_day,
        manual_refresh_per_day=manual_refresh_per_day,
        browser_fallback_allowed=browser_fallback_allowed,
    )


def _parse_cashback(cashback: dict[str, Any]) -> CashbackLimitValues | None:
    user_share = _decimal_value(cashback.get("user_share"))
    cashback_currency = cashback.get("cashback_currency")
    if user_share is None:
        return None
    if not isinstance(cashback_currency, str) or cashback_currency == "":
        return None
    return CashbackLimitValues(
        user_share=user_share,
        cashback_currency=cashback_currency,
    )


def _int_value(value: Any) -> int | None:
    if type(value) is not int:
        return None
    if value < 0:
        return None
    return value


def _decimal_value(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result
