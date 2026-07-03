from price_monitor.price_compare.live.adapters.base import LiveSearchItem, LiveStoreResult
from price_monitor.price_compare.live.merge import merge_live_results


def test_merge_filters_tv_accessories_for_tv_query() -> None:
    results = [
        LiveStoreResult(
            store_domain="fixture.test",
            status="ok",
            items=[
                LiveSearchItem(
                    title="Телевизор TCL 55C645",
                    price=39990,
                    url="https://fixture.test/tv",
                    availability="in_stock",
                ),
                LiveSearchItem(
                    title="Пульт для телевизора TCL",
                    price=690,
                    url="https://fixture.test/remote",
                    availability="in_stock",
                ),
            ],
            warnings=[],
        )
    ]

    merged = merge_live_results(results, query="телевизор", limit=10)

    assert [item.title for item in merged] == ["Телевизор TCL 55C645"]
