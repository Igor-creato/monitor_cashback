from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token_ref: str
    refresh_token_ref: str | None
    expires_at: int | None
    scopes: tuple[str, ...]


class MarketplaceOAuthProvider(Protocol):
    def build_authorization_url(self, *, state: str, redirect_uri: str, scopes: list[str]) -> str:
        """Build a user-consent URL for an official marketplace OAuth flow."""

    def exchange_authorization_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle:
        """Exchange an authorization code for a secret-managed token bundle."""
