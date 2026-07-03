from price_monitor.price_compare.live.adapters.base import LiveSearchQuery
from price_monitor.price_compare.live.adapters.fixture import FixtureSearchAdapter


def test_fixture_adapter_returns_current_store_result() -> None:
    adapter = FixtureSearchAdapter(
        domain="fixture.test",
        items=[
            {
                "title": "Телевизор TCL 55C645",
                "price": 39990,
                "url": "https://fixture.test/tcl-55",
                "availability": "in_stock",
            }
        ],
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "ok"
    assert result.store_domain == "fixture.test"
    assert result.items[0].title == "Телевизор TCL 55C645"
