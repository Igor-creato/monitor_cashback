from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    """Raised when a product URL violates the fail-closed public URL policy."""


@dataclass(frozen=True)
class ValidatedProductUrl:
    canonical_url: str
    canonical_url_hash: str
    source_domain: str


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "yclid"}
LOCAL_HOSTS = {"localhost", "localhost.localdomain", "internal"}


def validate_public_product_url(raw_url: str) -> ValidatedProductUrl:
    parsed = urlsplit(raw_url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError("only http and https product URLs are supported")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise UnsafeUrlError("product URL must include a host")
    if hostname in LOCAL_HOSTS or "." not in hostname:
        raise UnsafeUrlError("local hostnames are not allowed")

    _reject_private_ip_literal(hostname)

    port = parsed.port
    netloc = hostname
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"

    query = _canonical_query(parsed.query)
    canonical_url = urlunsplit((scheme, netloc, parsed.path or "/", query, ""))
    return ValidatedProductUrl(
        canonical_url=canonical_url,
        canonical_url_hash=sha256(canonical_url.encode("utf-8")).hexdigest(),
        source_domain=hostname,
    )


def _reject_private_ip_literal(hostname: str) -> None:
    candidate = hostname.strip("[]")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return

    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise UnsafeUrlError("private, local, or reserved IP addresses are not allowed")


def _canonical_query(query: str) -> str:
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS or lowered.startswith(TRACKING_QUERY_PREFIXES):
            continue
        pairs.append((key, value))
    return urlencode(sorted(pairs))
