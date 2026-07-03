import httpx

from price_monitor.price_compare.live.adapters.base import LiveSearchQuery
from price_monitor.price_compare.live.adapters.direct_http import DirectHttpSearchAdapter


def test_direct_http_adapter_stops_on_servicepipe_captcha() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>servicepipe captcha robot check</html>")

    adapter = DirectHttpSearchAdapter(
        domain="blocked.test",
        search_url_template="https://blocked.test/search?q={query}&city={city}",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "BLOCKED_BY_ANTIBOT"
    assert result.items == []
