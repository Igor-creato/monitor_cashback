from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from decimal import Decimal
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config
from app.main import app
from app.models.monitoring import ProductFeedItem, ProductFeedSource, Store, StoreSource

SITE_ID = "savelloclub.test"
USER_ID = "wp:savelloclub.test:123"
SECRET = "price-monitor-secret"
NOW = 1_781_516_800


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> Iterator[TestClient]:
    monkeypatch.setattr(config.settings, "price_monitor_incoming_site_id", SITE_ID)
    monkeypatch.setattr(
        config.settings,
        "price_monitor_incoming_secret",
        SecretStr(SECRET),
    )
    monkeypatch.setattr("app.core.incoming_hmac.current_unix_time", lambda: NOW)
    app.dependency_overrides[db.get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _signed_headers(site_id: str = SITE_ID) -> dict[str, str]:
    timestamp = str(NOW)
    signature = hmac.new(
        SECRET.encode(),
        f"{timestamp}.".encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Savello-Site": site_id,
        "X-Savello-Timestamp": timestamp,
        "X-Savello-Signature": signature,
    }


def _seed_search_sources(session: Session) -> None:
    dns = Store(store_code="dns", display_name="DNS", enabled=True)
    mvideo = Store(store_code="mvideo", display_name="М.Видео", enabled=True)
    disabled = Store(store_code="disabled", display_name="Disabled", enabled=True)
    session.add_all([dns, mvideo, disabled])
    session.flush()

    session.add_all(
        [
            StoreSource(
                store=dns,
                source_code="dns-feed",
                display_name="DNS feed",
                enabled=True,
                source_type="feed",
                domains_json=["dns-shop.ru"],
                search_template="https://www.dns-shop.ru/search/?q={query}&city={region}",
                region_support_json=["msk"],
                priority=10,
                extraction_mode="json",
                proxy_tier_policy="cheap_first",
                min_fetch_interval_minutes=60,
                matching_threshold=70,
            ),
            StoreSource(
                store=mvideo,
                source_code="mvideo-feed",
                display_name="М.Видео feed",
                enabled=True,
                source_type="feed",
                domains_json=["mvideo.ru"],
                search_template="https://www.mvideo.ru/product-list-page?q={query}",
                region_support_json=["default"],
                priority=20,
                extraction_mode="json",
                proxy_tier_policy="none",
                min_fetch_interval_minutes=60,
                matching_threshold=65,
            ),
            StoreSource(
                store=disabled,
                source_code="disabled-feed",
                display_name="Disabled feed",
                enabled=False,
                source_type="feed",
                domains_json=["disabled.example"],
                search_template="https://disabled.example/search?q={query}",
                region_support_json=["default"],
                priority=1,
                extraction_mode="json",
                proxy_tier_policy="none",
                min_fetch_interval_minutes=60,
                matching_threshold=65,
            ),
        ]
    )
    dns_feed = ProductFeedSource(
        merchant_id="dns",
        source_code="dns-feed",
        feed_url="https://feed.example/dns.yml",
        format="yml",
        currency="RUB",
        region_code="msk",
        enabled=True,
    )
    disabled_feed = ProductFeedSource(
        merchant_id="disabled",
        source_code="disabled-feed",
        feed_url="https://feed.example/disabled.yml",
        format="yml",
        currency="RUB",
        region_code="msk",
        enabled=True,
    )
    session.add_all([dns_feed, disabled_feed])
    session.flush()
    session.add_all(
        [
            ProductFeedItem(
                feed_source=dns_feed,
                external_product_id="iphone-15-128",
                canonical_url="https://www.dns-shop.ru/product/iphone-15",
                title="Смартфон Apple iPhone 15 128GB черный",
                image_url="https://cdn.example/iphone.jpg",
                price=Decimal("79990.00"),
                old_price=Decimal("84990.00"),
                currency="RUB",
                availability="in_stock",
                category_id="phone",
            ),
            ProductFeedItem(
                feed_source=disabled_feed,
                external_product_id="iphone-disabled",
                canonical_url="https://disabled.example/iphone",
                title="Смартфон Apple iPhone 15",
                price=Decimal("1.00"),
                currency="RUB",
                availability="in_stock",
            ),
        ]
    )
    session.commit()


def test_search_returns_enabled_feed_items_and_safe_source_fallbacks(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_search_sources(db_session)

    response = client.get(
        "/v1/price-assistant/search"
        f"?site_id={SITE_ID}&external_user_id={USER_ID}"
        "&q=%D1%81%D0%BC%D0%B0%D1%80%D1%82%D1%84%D0%BE%D0%BD%20iphone%2015"
        "&region_code=msk&limit=10",
        headers=_signed_headers(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "смартфон iphone 15"
    assert [item["source_code"] for item in data["items"]] == ["dns-feed"]
    assert data["items"][0] == {
        "store_code": "dns",
        "store_display_name": "DNS",
        "source_code": "dns-feed",
        "source_display_name": "DNS feed",
        "title": "Смартфон Apple iPhone 15 128GB черный",
        "product_url": "https://www.dns-shop.ru/product/iphone-15",
        "image_url": "https://cdn.example/iphone.jpg",
        "price": "79990.00",
        "old_price": "84990.00",
        "currency": "RUB",
        "availability": "in_stock",
        "match_label": "same_product",
        "match_score": 100,
        "search_url": "https://www.dns-shop.ru/search/?q="
        + quote("смартфон iphone 15")
        + "&city=msk",
        "is_fallback": False,
    }
    fallback_sources = {item["source_code"]: item for item in data["fallbacks"]}
    assert set(fallback_sources) == {"dns-feed", "mvideo-feed"}
    assert fallback_sources["mvideo-feed"]["search_url"] == (
        "https://www.mvideo.ru/product-list-page?q=" + quote("смартфон iphone 15")
    )
    assert "disabled-feed" not in response.text


def test_search_requires_hmac_and_matching_site_header(
    client: TestClient,
) -> None:
    no_hmac = client.get(
        f"/v1/price-assistant/search?site_id={SITE_ID}&external_user_id={USER_ID}&q=test"
    )
    wrong_site = client.get(
        f"/v1/price-assistant/search?site_id={SITE_ID}&external_user_id={USER_ID}&q=test",
        headers=_signed_headers(site_id="other-site.test"),
    )

    assert no_hmac.status_code == 401
    assert wrong_site.status_code == 403
