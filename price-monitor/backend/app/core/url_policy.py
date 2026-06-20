from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class UrlPolicyError(ValueError):
    pass


def validate_fetchable_http_url(
    value: str,
    *,
    allowed_domains: list[str] | None = None,
) -> str:
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UrlPolicyError("invalid_url")
    if parsed.username is not None or parsed.password is not None:
        raise UrlPolicyError("invalid_url")

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if hostname == "" or _is_blocked_hostname(hostname):
        raise UrlPolicyError("invalid_url")
    if allowed_domains is not None and not _host_matches_allowed_domain(
        hostname,
        allowed_domains,
    ):
        raise UrlPolicyError("invalid_url")
    return candidate


def _is_blocked_hostname(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
    )


def _host_matches_allowed_domain(hostname: str, domains: list[str]) -> bool:
    for domain in domains:
        normalized = domain.strip().lower().rstrip(".")
        if hostname == normalized or hostname.endswith(f".{normalized}"):
            return True
    return False
